#!/usr/bin/env bash
# Deploy the kit to a resource group. Needs: az (logged in), a resource group, and rights to create
# Entra app registrations. Nothing here has been run against a real subscription from this repository.
set -euo pipefail
RG=${RG:?resource group}
LOCATION=${LOCATION:-germanywestcentral}
NAME=${NAME:-cpokit}
ALERT_EMAIL=${ALERT_EMAIL:-}

# 1. Entra ID: the API (token audience, a user_impersonation scope for Power Platform and n8n),
#    the Teams bot, and group claims in tokens (the kit maps groups to functions and countries).
API_APP=$(az ad app create --display-name "$NAME-api" --identifier-uris "api://cpo-ai-deployment-kit" \
  --group-membership-claims SecurityGroup --query appId -o tsv)
BOT_APP=$(az ad app create --display-name "$NAME-teams-bot" --sign-in-audience AzureADMyOrg --query appId -o tsv)
echo "api app $API_APP, bot app $BOT_APP"

# 2. Image
az group create -n "$RG" -l "$LOCATION" -o none
PG_PASSWORD=$(openssl rand -base64 24)
ACR=$(az deployment group create -g "$RG" -f azure/main.bicep \
  -p name="$NAME" image=mcr.microsoft.com/k8se/quickstart:latest botAppId="$BOT_APP" pgAdminPassword="$PG_PASSWORD" \
     alertEmails="[\"$ALERT_EMAIL\"]" --query properties.outputs.acrLoginServer.value -o tsv)
az acr build -r "${ACR%%.*}" -t "cpo-ai-deployment-kit:$(git rev-parse --short HEAD)" .

# 3. Everything, with the real image
az deployment group create -g "$RG" -f azure/main.bicep \
  -p name="$NAME" image="$ACR/cpo-ai-deployment-kit:$(git rev-parse --short HEAD)" botAppId="$BOT_APP" \
     pgAdminPassword="$PG_PASSWORD" alertEmails="[\"$ALERT_EMAIL\"]" -o none

# 4. The database schema (row-level security, append-only usage events)
PG_HOST=$(az postgres flexible-server list -g "$RG" --query "[0].fullyQualifiedDomainName" -o tsv)
PGPASSWORD="$PG_PASSWORD" psql "host=$PG_HOST user=kitadmin dbname=kit sslmode=require" -f sql/kit.sql

# 5. Claude in Microsoft Foundry: deploy the models named in config/gateway.yaml from the model catalog
#    (Foundry portal > Models > Anthropic), then set CPOKIT_PROVIDER=foundry (already set in main.bicep).
echo "Deploy claude-haiku-5-5 and claude-sonnet-5-5 in the Foundry resource, then import"
echo "integrations/power-platform/apiDefinition.swagger.json as a custom connector and"
echo "integrations/n8n/dispute-intake.json into n8n."
