**Interim.** The chapter numbers come from the re-run on the full set around 10 Nov.

3892 observations, 139 logging runs, 2026-10-20T06:42:29 to 2026-10-26T15:07:01 EAT, cutoff 2026-10-26T13:00:00Z.
Bootstrap: 1000 resamples of runs, seed 103.

Internal check on trip_records (synthetic, 3000 held back): MAPE 8.72%, MAE 145 s.

| Hour band | n | Model | MAPE % | 95% CI | MAE s | Signed % | Under >10% % |
|---|---|---|---|---|---|---|---|
| all | 3892 | rf | 7.25 | 6.64 to 8.08 | 120 | +3.45 | 6.5 |
| all | 3892 | static_baseline | 16.39 | 15.00 to 17.81 | 257 | +9.49 | 12.3 |
| all | 3892 | l2_reference | 6.19 | 5.52 to 7.13 | 104 | +2.56 | 5.9 |
| night | 1428 | rf | 7.47 | 6.90 to 8.10 | 110 | +6.64 | 0.8 |
| night | 1428 | static_baseline | 20.99 | 18.84 to 22.83 | 287 | +20.53 | 0.4 |
| night | 1428 | l2_reference | 6.32 | 5.70 to 6.99 | 95 | +5.61 | 0.6 |
| morning | 728 | rf | 6.53 | 5.71 to 7.50 | 103 | +2.25 | 7.0 |
| morning | 728 | static_baseline | 17.25 | 14.53 to 20.30 | 240 | +15.09 | 3.4 |
| morning | 728 | l2_reference | 5.17 | 4.40 to 6.17 | 84 | +0.79 | 7.3 |
| midday | 1008 | rf | 6.24 | 5.64 to 6.92 | 109 | +1.30 | 8.4 |
| midday | 1008 | static_baseline | 9.14 | 7.83 to 10.62 | 146 | +4.37 | 9.5 |
| midday | 1008 | l2_reference | 5.31 | 4.79 to 5.96 | 95 | +0.71 | 7.2 |
| evening | 728 | rf | 8.96 | 6.67 to 12.93 | 172 | +1.35 | 14.4 |
| evening | 728 | static_baseline | 16.54 | 12.92 to 20.30 | 367 | -10.69 | 48.4 |
| evening | 728 | l2_reference | 8.17 | 5.55 to 12.76 | 156 | +0.92 | 13.0 |

RF minus static baseline, MAPE points (below 0: the RF is better):

| Hour band | Difference | 95% CI |
|---|---|---|
| all | -9.13 | -10.63 to -7.54 |
| night | -13.53 | -15.61 to -11.08 |
| morning | -10.71 | -13.66 to -8.23 |
| midday | -2.90 | -4.03 to -1.86 |
| evening | -7.58 | -12.51 to -1.68 |

| Zone | n | RF MAPE % | Baseline MAPE % | L2 MAPE % | RF under >10% % |
|---|---|---|---|---|---|
| Athi River, Machakos County | 139 | 6.13 | 17.95 | 5.41 | 7.9 |
| Buruburu, Nairobi | 139 | 6.32 | 15.51 | 4.56 | 7.2 |
| Dagoretti, Nairobi | 139 | 7.64 | 14.26 | 6.43 | 0.7 |
| Donholm, Nairobi | 139 | 6.25 | 12.13 | 5.10 | 2.9 |
| Embakasi, Nairobi | 139 | 7.13 | 20.67 | 6.48 | 10.8 |
| Imara Daima, Nairobi | 139 | 8.93 | 26.47 | 7.16 | 3.6 |
| Kahawa, Nairobi | 139 | 5.77 | 9.35 | 4.74 | 11.5 |
| Karen, Nairobi | 139 | 5.30 | 10.13 | 5.37 | 8.6 |
| Kasarani, Nairobi | 139 | 6.68 | 15.63 | 5.66 | 4.3 |
| Kawangware, Nairobi | 139 | 9.88 | 16.53 | 8.44 | 0.7 |
| Kayole, Nairobi | 139 | 4.98 | 7.48 | 3.62 | 0.7 |
| Kilimani, Nairobi | 139 | 7.84 | 19.74 | 6.37 | 8.6 |
| Kitengela, Kajiado County | 139 | 7.25 | 19.51 | 5.41 | 12.9 |
| Langata, Nairobi | 139 | 6.84 | 11.93 | 6.37 | 18.7 |
| Lavington, Nairobi | 139 | 10.23 | 22.78 | 9.43 | 2.2 |
| Mlolongo, Machakos County | 139 | 8.56 | 22.72 | 6.83 | 9.4 |
| Nairobi CBD, Nairobi | 139 | 10.43 | 23.53 | 9.41 | 24.5 |
| Ngara, Nairobi | 139 | 9.34 | 22.04 | 7.91 | 2.2 |
| Nyayo Estate, Nairobi | 139 | 3.85 | 7.12 | 3.45 | 2.2 |
| Ongata Rongai, Kajiado County | 139 | 6.68 | 13.47 | 6.06 | 10.1 |
| Roysambu, Nairobi | 139 | 7.54 | 15.70 | 5.62 | 10.8 |
| Ruiru, Kiambu County | 139 | 5.94 | 11.85 | 4.85 | 1.4 |
| Runda, Nairobi | 139 | 9.52 | 18.81 | 8.69 | 1.4 |
| South B, Nairobi | 139 | 6.30 | 15.93 | 4.87 | 4.3 |
| South C, Nairobi | 139 | 5.66 | 18.42 | 5.44 | 7.2 |
| Umoja, Nairobi | 139 | 4.48 | 9.00 | 3.69 | 0.7 |
| Upper Hill, Nairobi | 139 | 6.96 | 17.61 | 6.20 | 6.5 |
| Westlands, Nairobi | 139 | 10.72 | 22.63 | 9.82 | 0.0 |
