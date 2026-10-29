Counters, seed 1, 120 s with counting wrappers: 6 generations (the last may be partial).

- Travel calls: 20,226,142 (3,371,024 per generation).
- Departure searches: 881,863; steps after the first drive: mean 1.09, histogram 0: 376,981, 1: 200,788, 2: 213,062, 3: 41,569, 4: 44,443, 5: 74, 6: 2,775, 7: 1,202, 8: 803, 9: 148, 10: 18.
- Steps by how far the start lands from available_from: 0-1 h: 677,287 searches, mean 0.66 steps; 1-2 h: 130,479 searches, mean 2.25 steps; 2-3 h: 52,464 searches, mean 3.05 steps; 3-4 h: 16,854 searches, mean 3.09 steps; 4+ h: 4,779 searches, mean 2.93 steps.
- Positions fully costed per _best_position call (insertion): mean 5.56 over 153,166 calls.

| Generation | Route costings in | Count | Repeat a route costed earlier in the solve |
|---|---|---|---|
| 0 | outside the GA loop | 2,400 | 0.0% |
| 0 | initial population | 600 | 0.2% |
| 1 | crossover child | 600 | 11.7% |
| 1 | removal | 1,900 | 10.0% |
| 1 | insertion | 206,418 | 0.9% |
| 1 | mutated child | 600 | 100.0% |
| 2 | crossover child | 600 | 22.5% |
| 2 | removal | 3,643 | 11.4% |
| 2 | insertion | 169,563 | 2.1% |
| 2 | mutated child | 600 | 100.0% |
| 3 | crossover child | 600 | 21.7% |
| 3 | removal | 3,415 | 7.1% |
| 3 | insertion | 178,763 | 2.1% |
| 3 | mutated child | 600 | 100.0% |
| 4 | crossover child | 600 | 29.8% |
| 4 | removal | 4,692 | 11.8% |
| 4 | insertion | 109,030 | 3.8% |
| 4 | mutated child | 600 | 100.0% |
| 5 | crossover child | 600 | 33.7% |
| 5 | removal | 5,233 | 13.3% |
| 5 | insertion | 127,537 | 3.4% |
| 5 | mutated child | 600 | 100.0% |
| 6 | outside the GA loop | 20 | 100.0% |
| 6 | crossover child | 240 | 25.8% |
| 6 | removal | 1,858 | 8.6% |
| 6 | insertion | 61,416 | 3.3% |
| 6 | mutated child | 240 | 100.0% |

Of the mutated child's routes, 99.8% were costed by its own destroy and repair.
