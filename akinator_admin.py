import json
import os
import shutil
import difflib

DB_FILE = "akinator_prob_db.json"
BACKUP_FILE = "akinator_prob_db.backup.json"

# Internal bookkeeping keys that are NOT questions (kept in sync with akinator2.py)
META_KEYS = {"name", "_n"}

# Safety limits to guard against maliciously crafted / bloated database files
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_NAME_LEN = 100
MAX_QUESTION_LEN = 200
MAX_QUESTIONS_PER_CHARACTER = 500
LARGE_DB_WARNING_THRESHOLD = 2000  # dedup is O(n^2); warn above this size


def sanitize_text(value, max_len):
    """
    Strips non-printable/control characters (which also neutralizes things
    like ANSI terminal-escape injection attempts) and enforces a max length.
    Returns None if the value isn't a usable string.
    """
    if not isinstance(value, str):
        return None
    cleaned = "".join(ch for ch in value if ch.isprintable()).strip()
    if not cleaned:
        return None
    return cleaned[:max_len]


def sanitize_character(entry, index):
    """
    Validates and cleans a single database record. Returns a cleaned dict,
    or None if the record is unusable (missing/invalid name, wrong type,
    etc.), in which case it's dropped with a warning instead of crashing
    the whole script.
    """
    if not isinstance(entry, dict):
        print(f"  [!] Skipping record #{index}: not a valid object.")
        return None

    name = sanitize_text(entry.get("name"), MAX_NAME_LEN)
    if not name:
        print(f"  [!] Skipping record #{index}: missing or invalid 'name'.")
        return None

    clean = {"name": name}

    n_val = entry.get("_n", 1)
    if not isinstance(n_val, (int, float)) or isinstance(n_val, bool) or n_val <= 0:
        n_val = 1
    clean["_n"] = n_val

    dropped_fields = 0
    kept = 0
    for key, val in entry.items():
        if key in META_KEYS:
            continue
        if kept >= MAX_QUESTIONS_PER_CHARACTER:
            dropped_fields += 1
            continue

        q = sanitize_text(key, MAX_QUESTION_LEN)
        if not q:
            dropped_fields += 1
            continue
        if not q.endswith("?"):
            q += "?"

        if not isinstance(val, (int, float)) or isinstance(val, bool):
            dropped_fields += 1
            continue

        clean[q] = max(0.0, min(1.0, float(val)))
        kept += 1

    if dropped_fields:
        print(f"  [!] '{name}': dropped {dropped_fields} invalid/excess field(s).")

    return clean


def load_database():
    """Loads and sanitizes the database from the local file."""
    if not os.path.exists(DB_FILE):
        print(f"Error: Database file '{DB_FILE}' not found. Run the main game first.")
        return None

    try:
        file_size = os.path.getsize(DB_FILE)
    except OSError as e:
        print(f"Error: Could not read file size of '{DB_FILE}': {e}")
        return None

    if file_size > MAX_FILE_SIZE_BYTES:
        print(
            f"Error: '{DB_FILE}' is {file_size / (1024*1024):.1f} MB, which exceeds "
            f"the {MAX_FILE_SIZE_BYTES / (1024*1024):.0f} MB safety limit. "
            "Refusing to load (possible corrupted or maliciously bloated file)."
        )
        return None

    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: '{DB_FILE}' is not valid JSON ({e}). Aborting.")
        return None
    except OSError as e:
        print(f"Error: Could not read '{DB_FILE}': {e}")
        return None

    if not isinstance(raw_data, list):
        print(f"Error: '{DB_FILE}' does not contain a JSON list at the top level. Aborting.")
        return None

    print(f"Loaded {len(raw_data)} raw record(s); validating...")
    cleaned = []
    for i, entry in enumerate(raw_data):
        result = sanitize_character(entry, i)
        if result is not None:
            cleaned.append(result)

    dropped = len(raw_data) - len(cleaned)
    if dropped:
        print(f"Validation complete: {dropped} record(s) dropped, {len(cleaned)} kept.\n")
    else:
        print(f"Validation complete: all {len(cleaned)} record(s) passed.\n")

    return cleaned


def save_database(db):
    """Backs up the existing file (if any), then saves the cleaned database."""
    try:
        if os.path.exists(DB_FILE):
            shutil.copy2(DB_FILE, BACKUP_FILE)
    except OSError as e:
        print(f"Warning: could not create backup ({e}). Proceeding without one.")

    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=4)
    except OSError as e:
        print(f"Error: failed to save database: {e}")
        return
    print(f"Database successfully updated and saved! (backup at '{BACKUP_FILE}')")


def calculate_similarity(char1, char2):
    """
    Calculates a similarity score between two characters based on:
    1. Name similarity (using Gestalt Pattern Matching)
    2. Overlapping question score differences
    Returns a score from 0.0 (completely different) to 1.0 (identical).
    """
    name1 = char1["name"].lower()
    name2 = char2["name"].lower()
    name_sim = difflib.SequenceMatcher(None, name1, name2).ratio()

    # Exclude bookkeeping keys (e.g. "_n") from the question comparison —
    # previously only "name" was excluded, which meant "_n" was silently
    # treated as if it were a question trait and skewed similarity scores.
    shared_questions = [q for q in char1 if q not in META_KEYS and q in char2]

    if not shared_questions:
        ans_sim = 0.5
    else:
        total_diff = sum(abs(char1[q] - char2[q]) for q in shared_questions)
        avg_diff = total_diff / len(shared_questions)
        ans_sim = 1.0 - avg_diff

    combined_score = (name_sim * 0.4) + (ans_sim * 0.6)
    return combined_score


def merge_profiles(char1, char2):
    """
    Combines two character profiles, pooling questions. Shared questions are
    combined with a confidence-weighted average (using each character's "_n"
    observation count) rather than a flat 50/50 average, so a well-established
    profile isn't knocked around as much by a thinly-observed duplicate.
    """
    merged = {"name": char1["name"]}  # Keeps the first character's name casing

    n1 = char1.get("_n", 1)
    n2 = char2.get("_n", 1)
    merged["_n"] = n1 + n2

    all_qs = (set(char1.keys()) | set(char2.keys())) - META_KEYS

    for q in all_qs:
        if q in char1 and q in char2:
            merged[q] = (char1[q] * n1 + char2[q] * n2) / (n1 + n2)
        elif q in char1:
            merged[q] = char1[q]
        else:
            merged[q] = char2[q]

    return merged


def run_admin_dedup():
    db = load_database()
    if not db or len(db) < 2:
        print("Not enough valid characters in database.")
        return

    if len(db) > LARGE_DB_WARNING_THRESHOLD:
        print(
            f"Warning: database has {len(db)} records. Duplicate-checking is O(n^2) "
            "and may take a while.\n"
        )

    print("Analyzing database for duplicate entries...\n")

    modified = False
    i = 0
    while i < len(db):
        j = i + 1
        while j < len(db):
            try:
                score = calculate_similarity(db[i], db[j])
            except (TypeError, KeyError) as e:
                # A malformed record slipping through somehow shouldn't crash
                # the whole dedup pass — skip the comparison and move on.
                print(f"  [!] Skipping comparison at ({i}, {j}) due to bad data: {e}")
                j += 1
                continue

            if score > 0.65:  # Slight threshold increase for fewer false positives
                print(f"\n[Match Confidence: {score:.2%}]")
                print(f"  A: {db[i]['name']}")
                print(f"  B: {db[j]['name']}")

                choice = input("Are these the same character? (yes/no/skip): ").strip().lower()

                if choice == "yes":
                    merged = merge_profiles(db[i], db[j])
                    db[i] = merged
                    db.pop(j)
                    modified = True
                    print(f"Merged into '{merged['name']}'.")
                    # Restart comparison for current 'i' against updated list
                    continue
            j += 1
        i += 1

    if modified:
        save_database(db)
        print("\nDatabase successfully cleaned and saved!")
    else:
        print("\nNo duplicates merged.")


if __name__ == "__main__":
    try:
        run_admin_dedup()
    except KeyboardInterrupt:
        print("\nInterrupted. No changes were saved beyond the last successful merge.")
    except Exception as e:
        # Fail safe rather than crashing with a raw traceback on unexpected/
        # maliciously-crafted input.
        print(f"\nUnexpected error: {e}. Aborting without further changes.")
