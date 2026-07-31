import json
import os
import random
import math
from pathlib import Path

# File name for persistent storage
DB_FILE = str(Path(__file__).resolve().parent) + "/akinator_prob_db.json"

# Internal bookkeeping keys that are NOT questions (excluded from question extraction)
META_KEYS = {"name", "_n"}

# Default seed data to start the game
DEFAULT_DATA = [
    {
        "name": "Harry Potter",
        "_n": 1,
        "Is your character fictional?": 1.0,
        "Is your character a human?": 1.0,
        "Does your character use magic?": 1.0
    },
    {
        "name": "Albert Einstein",
        "_n": 1,
        "Is your character fictional?": 0.0,
        "Is your character a human?": 1.0,
        "Does your character use magic?": 0.0
    },
    {
        "name": "Mickey Mouse",
        "_n": 1,
        "Is your character fictional?": 1.0,
        "Is your character a human?": 0.0,
        "Does your character use magic?": 0.0
    }
]

def load_database():
    """Loads the database from a file or falls back to default data."""
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return json.load(f)
    return DEFAULT_DATA

def save_database(db):
    """Saves the active database back to the local file."""
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=4)

def get_all_questions(db):
    """Extracts every unique question text currently present in the database."""
    questions = set()
    for char in db:
        for key in char.keys():
            if key not in META_KEYS:
                questions.add(key)
    return list(questions)

def normalize_question(q_string):
    """
    Improvement C: Standardizes question text formatting.
    Capitalizes first letter, strips excess spaces, and ensures a trailing '?'.
    """
    q_string = q_string.strip()
    if not q_string:
        return ""
    q_string = q_string[0].upper() + q_string[1:]
    if not q_string.endswith("?"):
        q_string += "?"
    return q_string

def find_similar_question(new_q, existing_questions, threshold=0.6):
    new_tokens = set(new_q.lower().rstrip("?").split())
    if not new_tokens:
        return None

    best_match, best_score = None, 0.0
    for q in existing_questions:
        q_tokens = set(q.lower().rstrip("?").split())
        if not q_tokens:
            continue
        overlap = len(new_tokens & q_tokens) / len(new_tokens | q_tokens)
        if overlap > best_score:
            best_score, best_match = overlap, q

    return best_match if best_score >= threshold else None

def calculate_entropy(candidate_count):
    """Calculates Shannon entropy for a group size."""
    if candidate_count <= 1:
        return 0.0
    return math.log2(candidate_count)

def find_best_question(candidates, available_questions):
    if not available_questions or not candidates:
        return None

    best_q = None
    best_info_gain = -1.0
    current_entropy = calculate_entropy(len(candidates))

    for q in available_questions:
        # Split candidates based on trait probability value.
        # Tightened idk band (0.45-0.55) so near-yes/near-no traits count
        # toward their real side instead of diluting both groups.
        yes_group = [c for c in candidates if c.get(q, 0.5) >= 0.55]
        no_group = [c for c in candidates if c.get(q, 0.5) <= 0.45]
        idk_group = [c for c in candidates if 0.45 < c.get(q, 0.5) < 0.55]

        total = len(candidates)
        # Weighted entropy across splits
        weighted_entropy = (
            (len(yes_group) / total) * calculate_entropy(len(yes_group)) +
            (len(no_group) / total) * calculate_entropy(len(no_group)) +
            (len(idk_group) / total) * calculate_entropy(len(idk_group))
        )

        info_gain = current_entropy - weighted_entropy

        if info_gain > best_info_gain:
            best_info_gain = info_gain
            best_q = q

    return best_q if best_q else available_questions[0]

def compute_question_weights(db, questions):
    weights = {}
    for q in questions:
        values = [c[q] for c in db if q in c]
        if len(values) < 2:
            weights[q] = 0.5  # not enough data, treat as neutral
            continue
        mean_v = sum(values) / len(values)
        variance = sum((v - mean_v) ** 2 for v in values) / len(values)
        weights[q] = min(1.0, variance / 0.25)
    return weights

def score_candidate(candidate, session_answers, question_weights=None):
    if not session_answers:
        return 1.0

    total_diff = 0
    total_weights = 0

    for q, user_val in session_answers.items():
        cand_val = candidate.get(q, 0.5)
        # Give higher weight to decisive answers (yes=1.0, no=0.0) over neutral (idk=0.5)
        decisiveness = 1.0 if user_val in (0.0, 1.0) else 0.5

        informativeness = 1.0
        if question_weights is not None:
            # Scale 0.5x-1.5x based on how discriminating the question is,
            # so it never zeroes out a question entirely.
            informativeness = 0.5 + question_weights.get(q, 0.5)

        weight = decisiveness * informativeness

        total_diff += abs(cand_val - user_val) * weight
        total_weights += weight

    if total_weights == 0:
        return 1.0

    avg_diff = total_diff / total_weights
    return 1.0 - avg_diff

def merge_characters(existing_char, session_answers):
    n = existing_char.get("_n", 1)
    for q, ans_val in session_answers.items():
        if q in existing_char:
            existing_char[q] = (existing_char[q] * n + ans_val) / (n + 1)
        else:
            existing_char[q] = ans_val
    existing_char["_n"] = n + 1

def play_round():
    db = load_database()
    all_questions = get_all_questions(db)
    question_weights = compute_question_weights(db, all_questions)

    # Track current pool of active/probable candidates
    active_candidates = db.copy()

    # Track session answers: { question_text: answer_val }
    session_answers = {}
    asked_questions = []

    print("--- Think of a character and answer the questions! ---\n")

    # Set maximum questions cap dynamically
    max_questions = min(15, len(all_questions)) if all_questions else 0

    while len(asked_questions) < max_questions:
        remaining_qs = [q for q in all_questions if q not in asked_questions]

        # Pick the best question using Information Gain
        current_q = find_best_question(active_candidates, remaining_qs)
        if not current_q:
            break

        user_input = input(f"{current_q} (yes/no/idk): ").strip().lower()
        asked_questions.append(current_q)

        if user_input == "yes":
            ans_val = 1.0
        elif user_input == "no":
            ans_val = 0.0
        else:
            ans_val = 0.5

        session_answers[current_q] = ans_val

        # Soft filter: prune candidates whose current match score is extremely low (< 0.3)
        active_candidates = [
            c for c in active_candidates
            if score_candidate(c, session_answers, question_weights) >= 0.3
        ]

        # Improvement E: Margin check.
        # Stop early only if the top candidate is both confident AND clearly
        # ahead of the runner-up, instead of just checking pool size == 1.
        if active_candidates:
            scored = sorted(
                (score_candidate(c, session_answers, question_weights) for c in active_candidates),
                reverse=True
            )
            top_score = scored[0]
            margin = top_score - scored[1] if len(scored) > 1 else top_score
            if top_score >= 0.8 and margin > 0.15:
                break

    # If soft filtering pruned everyone, fall back to ranking the entire database
    candidates_to_rank = active_candidates if active_candidates else db

    # Sort candidates by match score descending
    candidates_to_rank.sort(
        key=lambda c: score_candidate(c, session_answers, question_weights),
        reverse=True
    )

    # --- SINGLE/TOP CANDIDATE PROFILING ---
    # Bug fix: previously this wrote the profiling answer directly onto the
    # live db object (top_candidate[extra_q] = val) BEFORE the player
    # confirmed the guess was correct. A wrong guess would still leave that
    # answer permanently baked into the character's profile. Now we only
    # record it in session_answers; it gets applied properly (via the
    # moving-average blend in merge_characters) if and only if the guess
    # is confirmed correct.
    if candidates_to_rank:
        top_candidate = candidates_to_rank[0]
        missing_qs = [q for q in all_questions if q not in top_candidate and q not in asked_questions]

        if missing_qs and len(asked_questions) < max_questions:
            print("\n[AI is profiling...] Asking a background question to complete data.")
            extra_q = random.choice(missing_qs)
            user_input = input(f"{extra_q} (yes/no/idk): ").strip().lower()
            val = 1.0 if user_input == "yes" else (0.0 if user_input == "no" else 0.5)
            session_answers[extra_q] = val
            # NOTE: no longer mutating top_candidate here. See comment above.

    # --- FINAL GUESSING & LEARNING LOGIC ---
    if candidates_to_rank:
        guess = candidates_to_rank[0]
        confidence = score_candidate(guess, session_answers, question_weights)

        is_correct = input(f"\nIs your character {guess['name']}? (Confidence: {confidence:.0%}) (yes/no): ").strip().lower()

        if is_correct == "yes":
            print("Awesome! I win.")
            merge_characters(guess, session_answers)
            save_database(db)
            return

    # If wrong or no candidates left, start the learning mechanism
    print("\nYou beat me! I don't know who you are thinking of.")
    correct_name = input("What was the name of your character? ").strip()

    if not correct_name:
        print("No name provided. Ending game.")
        return

    # Check if this character already exists under that name
    existing_match = next((c for c in db if c["name"].lower() == correct_name.lower()), None)

    if existing_match:
        same_check = input(f"I already have a '{existing_match['name']}'. Are they the same? (yes/no): ").strip().lower()
        if same_check == "yes":
            print("Merging your answers into their existing profile.")
            merge_characters(existing_match, session_answers)
            save_database(db)
            return

    # Create new character entry
    new_character = {"name": correct_name, "_n": 1}
    for q, val in session_answers.items():
        new_character[q] = val

    if candidates_to_rank:
        top_confusables = candidates_to_rank[:3]
        wrong_guess = top_confusables[0]

        for confusable in top_confusables:
            print(f"\nHelp me differentiate {correct_name} from {confusable['name']}.")
            raw_q = input(
                f"Type a question where the answer is YES for {correct_name}\n"
                f"but NO for {confusable['name']} (or press Enter to skip)\n"
                "Try to make the question as non-specific as possible: "
            )
            if not raw_q.strip():
                continue

            new_q = normalize_question(raw_q)

            similar = find_similar_question(new_q, all_questions)
            if similar:# and similar != new_q:
                same = input(f"Note: this looks similar to an existing question: \"{similar}\" — should i use that instead? (Y/n): ")
                if same.lower() == 'y':
                    new_q = similar

            new_character[new_q] = 1.0
            merge_characters(confusable, {new_q: 0.0})

        db.append(new_character)
        save_database(db)
        print(f"Learned '{correct_name}' successfully and saved to file!")
        return

    db.append(new_character)
    save_database(db)
    print(f"Learned '{correct_name}' successfully and saved to file!")

if __name__ == "__main__":
    while True:
        play_round()
        play_another = input("Play another round? (Y/n): ")
        if play_another.lower() == 'n':
            break
    print ("Goodbye!")
