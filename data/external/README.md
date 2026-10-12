# data/external — temp third-party datasets (NOT shipped, gitignored)

## ibm-hr-attrition.csv
- Source: IBM HR Analytics Employee Attrition & Performance (Kaggle:
  `pavansubhasht/ibm-hr-analytics-attrition-dataset`), via trusted publisher
  mirror `PacktPublishing/Statistics-for-Machine-Learning`
  (`Chapter04/WA_Fn-UseC_-HR-Employee-Attrition.csv`, 227,974 bytes).
- Verified 2026-10-12: 1470 rows × 35 cols, MonthlyIncome 1009/4919/19999
  (min/med/max). Key cols for temp checks: EmployeeNumber, Department,
  MonthlyIncome, OverTime, PercentSalaryHike.
- Use: ad-hoc realism checks only (e.g. feed MonthlyIncome into tds_simulate,
  EmployeeNumber into ID regex). NEVER wired into `db/seed.py` — the
  deterministic seed stays the test contract. Redownload: raw URL in git
  history (PR #14); file itself is gitignored.
