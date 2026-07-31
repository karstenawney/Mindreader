# Mindreader
A locally-run character guessing game inspired by Akinator.
Designed to build itself over time. 
Feel free to fork and pull to add your new akinator_prob_db.json file. 
Any increase in the db content is welcome. 

---Scalability---
Here is the Big O scalability equations: 

Key Variables
N: Total number of characters
Q: Total number of unique questions
L: Average number of questions per character
K: Maximum questions asked in a single game session (15 or Q, whichever is less)
T: Average question length

Game Initialization
O(N(L + Q))

Game Loop
O(KN(Q + K))

Post Game (Learning Phase)
O(NK + N log N + QT)



Total Complexity
O(N(L + Q + K(Q + K) + K) + N log N + QT)

Dominant Total Complexity
O(NQ)

Admin Script Complexity: 
O(N^2)
