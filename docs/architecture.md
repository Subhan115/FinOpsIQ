
# Architecture

## 1. Overview

**What this system does:**  
FinOpsIQ is an Azure-based FinOps monitoring project that detects unusual cloud-cost increases and explains them in plain language. Azure Cost Management exports daily cost data as CSV files to Azure Blob Storage, where an Azure Function App processes the data, detects percentage-based cost spikes, and uses Azure AI Foundry to generate an explanation of the likely cost drivers and recommended actions. Logic Apps then sends cost-spike alerts and a weekly manager-friendly scorecard.

The user does not need to define a fixed dollar budget. Instead, they define the percentage above their normal cost baseline that should be treated as a spike—for example, “alert me if daily cost is more than 50% above normal.”

**Main goals:**  
- Build an end-to-end Azure serverless FinOps solution using Terraform and Python  
- Detect daily Azure cost anomalies based on a user-defined percentage above a normal spending baseline  
- Generate simple, business-friendly AI explanations of detected cost spikes  
- Send automated cost-spike alerts through Azure Logic Apps  
- Generate a short weekly scorecard for engineering managers  
- Support multiple Azure subscriptions through one Function App  
- Provide a safe test mode using fictional CSV files, without waiting for daily Azure Cost Management exports  
- Apply Azure security practices through Managed Identity, Entra ID, Key Vault, and least-privilege RBAC  
- Store raw cost data, anomaly records, and scorecards with a 90-day retention policy  

**Out of scope (non-goals):**  
- Real-time or minute-by-minute Azure cost detection  
- Replacing Azure Budgets, Azure Cost Management, or Azure Advisor  
- Creating a custom web dashboard in the MVP  
- Automatically deleting, resizing, or changing Azure resources based on cost findings  
- Advanced machine-learning anomaly detection or training a custom ML model  
- Multi-region high availability or enterprise-scale disaster recovery  
- Full CI/CD pipelines in the initial MVP  
- Supporting thousands of tenant organizations or complex external SaaS billing  

---

## 2. High-level Diagram

```text
                                   ┌─────────────────────────────┐
                                   │         Entra ID            │
                                   │ Identity and RBAC control   │
                                   └──────────────┬──────────────┘
                                                  │
                                                  │ Managed Identity
                                                  ▼
┌───────────────────────────┐          ┌─────────────────────────────┐
│ Azure Cost Management     │          │        Azure Key Vault       │
│                           │          │ AI/service secrets if needed │
│ Daily cost export as CSV  │          └──────────────┬──────────────┘
└─────────────┬─────────────┘                         │
              │                                       │
              │ Production cost CSV                   │
              ▼                                       │
┌───────────────────────────────────────────────────────────────────┐
│                         Azure Blob Storage                         │
│                                                                   │
│  INPUT — monitored by the Function App                            │
│  ├── raw-cost-input/prod/                                         │
│  │   └── Daily CSV exported by Azure Cost Management              │
│  │                                                                │
│  └── raw-cost-input/test/                                         │
│      └── User-uploaded fictional FinOpsIQ test CSV                │
│                                                                   │
│  OUTPUT — never used as a Function trigger                        │
│  └── finopsiq-results/                                            │
│      ├── prod/anomalies/                                          │
│      ├── prod/scorecards/                                         │
│      ├── test/anomalies/                                          │
│      └── test/scorecards/                                         │
└──────────────────────────────┬────────────────────────────────────┘
                               │
                               │ New production or test CSV
                               │ Blob-triggered execution
                               ▼
┌───────────────────────────────────────────────────────────────────┐
│                   Azure Function App — Python                     │
│                                                                   │
│  1. Reads the uploaded/exported cost CSV                          │
│  2. Identifies production or test mode from the Blob path         │
│  3. Calculates the normal cost baseline                           │
│  4. Applies the user-defined spike percentage threshold           │
│  5. Finds top cost-driving subscriptions, services, or resources  │
│  6. Generates anomaly records and weekly scorecard data           │
│  7. Saves results to finopsiq-results/                            │
└───────────────────────┬─────────────────────────┬─────────────────┘
                        │                         │
                        │ Spike context           │ Anomaly records,
                        │                         │ scorecards
                        ▼                         ▼
          ┌─────────────────────────┐    ┌───────────────────────────┐
          │ Azure AI Foundry        │    │ Azure Blob Storage        │
          │                         │    │ finopsiq-results/         │
          │ Generates free-text     │    │                           │
          │ cost explanation and    │    │ 90-day retention policy   │
          │ suggested actions       │    └───────────────────────────┘
          └────────────┬────────────┘
                       │
                       │ AI explanation and weekly summary
                       ▼
          ┌─────────────────────────┐
          │ Azure Logic Apps        │
          │                         │
          │ Sends notifications     │
          └────────────┬────────────┘
                       │
          ┌────────────┴───────────────────────────────┐
          │                                            │
          ▼                                            ▼
┌───────────────────────────┐              ┌───────────────────────────┐
│ Cost spike alert          │              │ Weekly manager scorecard  │
│ Email or Microsoft Teams  │              │ Email or Microsoft Teams  │
│                           │              │                           │
│ Production: real alert    │              │ Short 1–2 minute summary  │
│ Test: [TEST] alert        │              │ of risks and opportunities│
└───────────────────────────┘              └───────────────────────────┘


                    ┌─────────────────────────────────┐
                    │ Application Insights + Monitor  │
                    │                                 │
                    │ Function logs, errors, metrics, │
                    │ execution duration, diagnostics │
                    └─────────────────────────────────┘
```


______________________________________________________________________

## 3. Production Data Flow

In production, FinOpsIQ receives cost data only from **Azure Cost Management**. Azure Cost Management creates a daily CSV export and places it in the production input location in Azure Blob Storage.

The Azure Function App does not receive the CSV directly from Cost Management. Instead, Cost Management writes the file to Blob Storage, and the Function App reads the file after it appears in the configured production input path.

```text
Azure Cost Management
        ↓
Daily CSV export
        ↓
raw-cost-input/prod/
        ↓
Azure Function App processes the CSV
        ↓
AI Foundry explains detected spikes
        ↓
Logic Apps sends alert if required
        ↓
Function saves anomaly records and scorecards
        ↓
finopsiq-results/prod/
```


### Production processing steps

1. Azure Cost Management exports daily cost data as a CSV file.
2. The CSV file is placed in `raw-cost-input/prod/`.
3. The Blob upload triggers the Azure Function App.
4. The Function reads the daily cost data and historical cost data required for baseline calculation.
5. The Function calculates whether the current daily cost is above the configured percentage threshold.
6. If a spike is detected, the Function identifies the biggest cost-driving services, resource groups, or resources.
7. The Function sends structured cost context to Azure AI Foundry.
8. Azure AI Foundry returns a free-text explanation and suggested next actions.
9. The Function sends the result to Azure Logic Apps.
10. Logic Apps sends a cost-spike alert through the selected notification channel, such as email or Microsoft Teams.
11. The Function stores anomaly records and generated scorecards in `finopsiq-results/prod/`.

______________________________________________________________________

## 4. Test Data Flow

FinOpsIQ includes fictional sample CSV files in the GitHub repository. These allow the project owner or user to test cost-spike detection, AI explanations, Logic Apps notifications, and weekly scorecards without waiting 24 hours for the next Azure Cost Management export.

```text
FinOpsIQ GitHub repository
        ↓
sample-data/finopsiq-demo-costs-spike.csv
        ↓
User uploads the file manually
        ↓
raw-cost-input/test/
        ↓
Azure Function App processes it in test mode
        ↓
Azure AI Foundry generates a test explanation
        ↓
Logic Apps sends a [TEST] notification
        ↓
Function stores test results
        ↓
finopsiq-results/test/
```


### Test processing steps

1. The user downloads a fictional sample CSV from the project repository.
2. The user uploads the file to `raw-cost-input/test/`.
3. The Blob upload triggers the same Azure Function App used for production.
4. The Function identifies the file as test data from the Blob path.
5. The Function runs the same cost-analysis, spike-detection, AI, reporting, and notification logic.
6. All notifications clearly begin with `[TEST]` or `[DEMO]`.
7. Test anomaly records and scorecards are saved only in `finopsiq-results/test/`.
8. Test data never changes production baselines, production anomaly records, or production reports.

### Sample data included in the repository

```text
sample-data/
├── README.md
├── finopsiq-demo-costs-no-spike.csv
├── finopsiq-demo-costs-spike.csv
└── finopsiq-demo-weekly-scorecard.csv
```

| Sample file | Purpose | Expected outcome |
| :-- | :-- | :-- |
| `finopsiq-demo-costs-no-spike.csv` | Tests normal spending variation | No cost-spike alert |
| `finopsiq-demo-costs-spike.csv` | Tests a major daily cost increase | `[TEST]` cost-spike alert and AI explanation |
| `finopsiq-demo-weekly-scorecard.csv` | Tests weekly aggregation and reporting | `[TEST]` weekly manager scorecard |


______________________________________________________________________

## 5. Loop Prevention and Storage Design

The architecture must avoid an event-processing loop.

A Blob-triggered Function runs when a new file is added or updated in the location that it monitors. Therefore, the Function must never write its result files into the same input location it watches.

```text
Correct design:

Input location monitored by Function
raw-cost-input/prod/
raw-cost-input/test/
        ↓
Function App processes CSV
        ↓
Output location not monitored by Function
finopsiq-results/prod/
finopsiq-results/test/
```

Because `finopsiq-results/` is not monitored by the Blob trigger, writing anomaly records and weekly reports does not invoke the Function again.

```text
Incorrect design — creates a loop:

raw-cost-input/
        ↓
Function App
        ↓
Function writes report back to raw-cost-input/
        ↓
Function is triggered again
        ↓
Repeated processing loop
```


### Storage rules

- The Function only listens to `raw-cost-input/prod/` and `raw-cost-input/test/`.
- Azure Cost Management writes production cost exports only to `raw-cost-input/prod/`.
- Users upload sample test CSV files only to `raw-cost-input/test/`.
- The Function writes production outputs only to `finopsiq-results/prod/`.
- The Function writes test outputs only to `finopsiq-results/test/`.
- No Function trigger is configured for `finopsiq-results/`.
- Blob lifecycle policies retain input and result data for 90 days.

______________________________________________________________________

## 6. Core Azure Services

| Layer | Azure service | Responsibility |
| :-- | :-- | :-- |
| Cost data source | Azure Cost Management + Billing | Generates daily Azure cost exports as CSV files |
| Storage | Azure Blob Storage | Stores production/test input CSVs, anomaly records, and scorecards |
| Compute | Azure Function App | Runs Python cost analysis, spike detection, AI integration, and report generation |
| AI | Azure AI Foundry | Produces free-text explanations of spikes and recommended actions |
| Notifications | Azure Logic Apps | Sends alerts and weekly reports through email or Microsoft Teams |
| Security | Azure Key Vault | Stores secrets only where managed identity cannot be used |
| Identity | Microsoft Entra ID + Managed Identity | Authenticates the Function App to Azure services without hard-coded credentials |
| Monitoring | Azure Monitor + Application Insights | Captures Function logs, errors, performance data, and execution metrics |
| Infrastructure as Code | Terraform | Provisions Azure resources with reusable and DRY Terraform modules |


______________________________________________________________________

## 7. Security Model

FinOpsIQ uses a system-assigned Managed Identity for the Azure Function App. The Function authenticates to Azure services through Microsoft Entra ID rather than storing credentials in source code.

The Function should use least-privilege Azure RBAC permissions:

- Read access to the required Blob Storage input locations
- Write access to the FinOpsIQ result locations
- Access to secrets in Azure Key Vault only when necessary
- Permission to call the selected Azure AI Foundry deployment
- Permission to invoke the Logic Apps notification workflow

Secrets, API keys, connection strings, and other sensitive values must not be committed to GitHub. Azure Key Vault is used only for values that cannot be replaced by Managed Identity authentication.

______________________________________________________________________

## 8. Monitoring and Observability

Application Insights and Azure Monitor provide visibility into FinOpsIQ operations.

Important events and metrics include:

- Function executions and execution duration
- Successful and failed CSV processing runs
- Number of cost spikes detected
- Number of AI Foundry requests
- AI request failures or latency
- Logic Apps notification failures
- Production versus test-mode execution count
- Blob filename and processing timestamp
- Weekly scorecard generation status

The Function should log whether each execution is running in `prod` or `test` mode. This makes troubleshooting easier and prevents accidental confusion between real cost alerts and demo/test alerts.

```
```

