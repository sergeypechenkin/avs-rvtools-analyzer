# Azure OpenAI Integration

This document describes the Azure OpenAI integration feature added to AVS RVTools Analyzer.

## Overview

The Azure OpenAI integration provides AI-powered risk analysis suggestions to help users understand and mitigate Azure VMware Solution migration risks. This feature enhances the existing risk detection capabilities with intelligent recommendations through environment variable configuration.

## Prerequisites

Before using the Azure OpenAI integration, you need to set up the following Azure resources:

### 1. Azure OpenAI Resource

Create an Azure OpenAI resource in your Azure subscription:

1. **Sign in to Azure Portal**: Go to [portal.azure.com](https://portal.azure.com)
2. **Create Resource**: Search for "Azure OpenAI" and click "Create"
3. **Configure Settings**:
   - Choose your subscription and resource group
   - Select a region (ensure it supports Azure OpenAI)
   - Choose a pricing tier
4. **Complete Creation**: Review and create the resource

**Documentation**: [Create and deploy an Azure OpenAI Service resource](https://docs.microsoft.com/en-us/azure/cognitive-services/openai/how-to/create-resource)

### 2. Model Deployment

Deploy a compatible language model in your Azure OpenAI resource:

1. **Navigate to Azure OpenAI Studio**: From your resource, click "Go to Azure OpenAI Studio"
2. **Create Deployment**:
   - Go to "Deployments" → "Create new deployment"
   - Choose a model (recommended: `gpt-4.1`, `gpt-4-turbo`, or `gpt-35-turbo`)
   - Provide a deployment name (e.g., "gpt-4.1")
   - Configure capacity settings
3. **Note the Deployment Name**: You'll need this for configuration

**Documentation**: [Deploy a model with Azure OpenAI](https://docs.microsoft.com/en-us/azure/cognitive-services/openai/how-to/create-resource?pivots=web-portal#deploy-a-model)

### 3. Microsoft Entra ID Access

Authentication uses `DefaultAzureCredential` and automatically refreshed Microsoft Entra ID
bearer tokens, not API keys.

1. **Endpoint URL**: Copy it from your Azure OpenAI resource overview (e.g., `https://your-resource.openai.azure.com/`).
2. **Permissions**: Have an administrator assign **Cognitive Services OpenAI User** to your signed-in user
   (local development) or to the application's managed identity (Azure hosting), scoped to this resource.
   Subscription Owner, Contributor, Reader, or User Access Administrator alone does not grant
   model inference data actions. Administrative resource access is not the same as permission
   to call the model.
3. **Propagation**: Allow time for role assignments to take effect.

**Documentation**: [Keyless connections to Azure AI services](https://learn.microsoft.com/azure/developer/ai/keyless-connections)

## Configuration

The endpoint and deployment are configured through environment variables. Authentication runs on the
server through Azure Identity. There is no web sign-in or subscription-selection form; all web and
API requests use the server's identity, not the browser user's identity.

### Local Sign-In and Subscription Selection

Install [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli), then sign in and choose
the subscription containing your Azure OpenAI resource:

```powershell
az login
az account list --output table
az account set --subscription "<subscription-name-or-id>"
```

For a resource in another tenant, use `az login --tenant "<tenant-id>"` before selecting the subscription.

Set the following in the same terminal from which you start the application:

```powershell
$env:AZURE_TOKEN_CREDENTIALS="AzureCliCredential"
$env:AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com/"
$env:AZURE_OPENAI_DEPLOYMENT_NAME="gpt-4.1"
avs-rvtools-analyzer
```

`DefaultAzureCredential` reuses your Azure CLI login. Setting `AZURE_TOKEN_CREDENTIALS=AzureCliCredential`
ensures another credential in the default chain cannot take precedence over your selected login.
If omitted, the standard credential chain is used, including developer credentials and managed identity.
Tokens are requested for `https://cognitiveservices.azure.com/.default` and refreshed automatically.

Selecting a subscription sets the Azure CLI account context; it does **not** discover an OpenAI
resource or update the endpoint/deployment. Set these explicitly for your chosen resource.
Restart the application after switching accounts, tenants, or environment configuration.

### Using .env File (Development)

For development environments, create a `.env` file in the project root:

```env
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4.1
AZURE_TOKEN_CREDENTIALS=AzureCliCredential
```

Run `az login` and `az account set` before starting the application. Do not store tokens or credentials
in this file. Remove legacy `AZURE_OPENAI_API_KEY` / `OPENAI_API_KEY` entries.
Also remove `AZURE_OPENAI_AD_TOKEN` if previously set. Legacy key and static-token variables are
ignored: the OpenAI client is explicitly configured with the refreshable token provider.

### Foundry Endpoints and GPT-5 Models

`AZURE_OPENAI_ENDPOINT` accepts either an Azure OpenAI resource endpoint
(`https://your-resource.openai.azure.com/`), a Foundry resource endpoint
(`https://your-resource.services.ai.azure.com/`), or the corresponding `/openai/v1/` base URL.
Use the **resource** endpoint, not a project URL under `/api/projects/`.
The service uses the OpenAI v1 API, so no dated API version is required.

Requests use `max_completion_tokens` and omit `temperature` to support reasoning models such as
GPT-5 as well as compatible chat models, regardless of the deployment's chosen name.
The model's default temperature is used instead of the previous fixed sampling setting.
Set `AZURE_OPENAI_MAX_TOKENS` to control the completion budget (default: `2000`).
For reasoning models, this budget includes reasoning tokens; increase it if no visible answer
is produced. Empty suggestions are reported as failures, not successful responses.

### Azure Hosting with Managed Identity

1. Enable a system-assigned managed identity on the Azure service hosting this application, or attach
   a user-assigned managed identity.
2. Grant that identity **Cognitive Services OpenAI User** on the target Azure OpenAI resource.
3. Configure `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_DEPLOYMENT_NAME` as application settings.
4. Set `AZURE_TOKEN_CREDENTIALS=ManagedIdentityCredential` to restrict the credential chain to managed
   identity in production, without falling back to developer logins.
5. For a user-assigned identity, also set `AZURE_CLIENT_ID` to its **client ID**, not its object ID.
   Omit this setting for a system-assigned identity.

Managed identity is available only on supported Azure hosts. It does not replace `az login` on a
local computer. The `azure-identity>=1.24.0` dependency supports selecting individual credentials
through `AZURE_TOKEN_CREDENTIALS`.

**Documentation**: [Azure Identity credential chains](https://learn.microsoft.com/azure/developer/python/sdk/authentication/credential-chains)

### Troubleshooting

- **No credential available**: Run `az login` in the same local environment as the application and
  set `AZURE_TOKEN_CREDENTIALS=AzureCliCredential`.
- **403 Forbidden**: Verify the user or managed identity has **Cognitive Services OpenAI User** on
  the target resource and that network access to the resource is permitted.
- **Wrong tenant/account**: Sign in with `az login --tenant "<tenant-id>"`, select the subscription,
  and restart the application.
- **Deployment not found**: Check that the deployment name belongs to the configured endpoint.
- **500 / Unable to get resource information, or 408 from Azure**: These are upstream inference
  failures. Confirm that the resource and deployment are ready, check Azure Service Health, and
  retain the Azure request ID when escalating. Successful local startup or token acquisition does
  not establish that the model endpoint is healthy. Upstream error details are returned in the AI
  suggestion's error response rather than hidden behind a generic failure message.
- **AI buttons visible but inference fails**: Configuration status indicates that the client has been
  initialized, not that credentials, RBAC, network connectivity, or the deployment have been validated.
  Tokens are obtained on the first AI request; failures are logged server-side and the request reports failure.

## Features

### 1. Environment Variable Configuration

- **Server-Side**: Configure Azure OpenAI using `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_DEPLOYMENT_NAME`, with keyless Azure Identity authentication
- **Automatic Detection**: Service automatically detects environment configuration and enables AI functionality
- **.env File Support**: Development-friendly configuration using `.env` files

### 2. AI-Powered Suggestions

- **Per-Risk Analysis**: Each detected risk can receive AI-powered suggestions by clicking "AI Suggestion" buttons
- **Direct HTML Output**: AI generates recommendations with HTML markup
- **Comprehensive Analysis**: AI provides impact assessment, recommended actions, migration strategy, and timeline considerations
- **Contextual Recommendations**: AI analyzes the specific risk data to provide relevant suggestions

### 3. User Experience

- **AI related Disclaimer**: Prominent warning about AI-generated content appears when AI functionality is available
- **Loading States**: Visual feedback during AI suggestion generation
- **Error Handling**: Graceful error handling for API failures

## Usage

### Setup

1. **Sign In and Configure**: Use Azure CLI locally or enable managed identity in Azure, then configure the endpoint and deployment as described above
2. **Start the Application**: Run the AVS RVTools Analyzer application
3. **Automatic Detection**: The application will automatically detect the Azure OpenAI configuration and enable AI functionality

### Getting AI Suggestions

1. **Upload RVTools Data**: Upload your RVTools Excel file through the web interface
2. **Review Detected Risks**: The application will analyze your data and display detected migration risks
3. **Generate AI Suggestions**: Click the "AI Suggestion" button on any risk card you want to analyze
4. **Review Analysis**: Wait for the AI to generate the analysis (typically 2-10 seconds) and review the comprehensive suggestions provided
5. **Use Results**: Apply the AI recommendations to your migration planning process

### Visual Indicators

When Azure OpenAI is properly configured via environment variables:

- **Disclaimer Visible**: A prominent disclaimer about AI-generated content appears at the top
- **AI Suggestion Buttons**: "AI Suggestion" buttons appear on each risk card
- **Loading States**: Buttons show loading indicators while generating suggestions
