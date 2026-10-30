// The kit on Azure: the API, the MCP servers and the Teams bot as Container Apps; PostgreSQL for
// proposals, approvals and usage events (row-level security, sql/kit.sql); Key Vault for the approval
// signing secret; Microsoft Foundry for Claude; Azure Bot Service for Teams; Application Insights for
// the OpenTelemetry traces; a budget on the resource group. Entra ID app registrations (the API's
// audience, the Teams bot, the Power Platform connector) are created by azure/deploy.sh.

targetScope = 'resourceGroup'

@description('Short name used in resource names')
param name string = 'cpokit'
param location string = resourceGroup().location
@description('Container image of the kit, e.g. <acr>.azurecr.io/cpo-ai-deployment-kit:<sha>')
param image string
@description('Entra ID tenant the tokens come from')
param tenantId string = subscription().tenantId
@description('Application ID URI of the kit API (the token audience)')
param apiAudience string = 'api://cpo-ai-deployment-kit'
@description('Microsoft App ID of the Teams bot (Entra app registration)')
param botAppId string
@secure()
@description('PostgreSQL administrator password (stored only in Key Vault)')
param pgAdminPassword string
@description('Monthly budget for the resource group in EUR')
param monthlyBudgetEur int = 300
param budgetStart string = '2026-11-01'
param alertEmails array = []

var mcpSystems = ['csms', 'roaming', 'payments', 'erp', 'documents', 'kit']

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${name}-logs'
  location: location
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${name}-insights'
  location: location
  kind: 'web'
  properties: { Application_Type: 'web', WorkspaceResourceId: logs.id }
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${name}-id'
  location: location
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: '${name}-kv-${uniqueString(resourceGroup().id)}'
  location: location
  properties: {
    tenantId: tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    enablePurgeProtection: true
  }
}

resource approvalSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'approval-secret'
  properties: { value: guid(resourceGroup().id, 'approval', name) }
}

resource pgSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'database-url'
  properties: { value: 'postgresql://kitadmin:${pgAdminPassword}@${pg.properties.fullyQualifiedDomainName}:5432/kit?sslmode=require' }
}

// Key Vault Secrets User for the app identity
resource kvRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vault
  name: guid(vault.id, identity.id, 'secrets-user')
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource pg 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: '${name}-pg-${uniqueString(resourceGroup().id)}'
  location: location
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    version: '16'
    administratorLogin: 'kitadmin'
    administratorLoginPassword: pgAdminPassword
    storage: { storageSizeGB: 32 }
    backup: { backupRetentionDays: 14, geoRedundantBackup: 'Disabled' }
    authConfig: { activeDirectoryAuth: 'Enabled', passwordAuth: 'Enabled', tenantId: tenantId }
  }
}

resource pgDb 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: pg
  name: 'kit'
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: '${name}acr${uniqueString(resourceGroup().id)}'
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, identity.id, 'acrpull')
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Microsoft Foundry (AI Services) for Claude; the model deployments are made in the Foundry portal or
// with azure/deploy.sh, as Anthropic models are deployed from the model catalog.
resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: '${name}-foundry-${uniqueString(resourceGroup().id)}'
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: '${name}-foundry-${uniqueString(resourceGroup().id)}'
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
  }
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${name}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: { customerId: logs.properties.customerId, sharedKey: logs.listKeys().primarySharedKey }
    }
  }
}

var commonEnv = [
  { name: 'CPOKIT_PROVIDER', value: 'foundry' }
  { name: 'CPOKIT_FOUNDRY_RESOURCE', value: foundry.name }
  { name: 'CPOKIT_JWKS_URL', value: '${environment().authentication.loginEndpoint}${tenantId}/discovery/v2.0/keys' }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: insights.properties.ConnectionString }
  { name: 'CPOKIT_APPROVAL_SECRET', secretRef: 'approval-secret' }
  { name: 'CPOKIT_DATABASE_URL', secretRef: 'database-url' }
  { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
]
var secrets = [
  { name: 'approval-secret', keyVaultUrl: approvalSecret.properties.secretUri, identity: identity.id }
  { name: 'database-url', keyVaultUrl: pgSecret.properties.secretUri, identity: identity.id }
]

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${name}-api'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: { external: true, targetPort: 8000, transport: 'auto' }
      registries: [{ server: acr.properties.loginServer, identity: identity.id }]
      secrets: secrets
    }
    template: {
      containers: [{
        name: 'api'
        image: image
        command: ['cpokit', 'serve-api']
        env: commonEnv
        resources: { cpu: json('0.5'), memory: '1Gi' }
        probes: [{ type: 'Liveness', httpGet: { path: '/health', port: 8000 } }]
      }]
      scale: { minReplicas: 1, maxReplicas: 4 }
    }
  }
  dependsOn: [kvRole, acrPull]
}

resource mcp 'Microsoft.App/containerApps@2024-03-01' = [for system in mcpSystems: {
  name: '${name}-mcp-${system}'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: { external: false, targetPort: 8100, transport: 'http' }
      registries: [{ server: acr.properties.loginServer, identity: identity.id }]
      secrets: secrets
    }
    template: {
      containers: [{
        name: 'mcp'
        image: image
        command: ['cpokit', 'serve-mcp', system]
        env: concat(commonEnv, [{ name: 'CPOKIT_PUBLIC_URL', value: 'https://${name}-mcp-${system}.internal.${env.properties.defaultDomain}' }])
        resources: { cpu: json('0.25'), memory: '0.5Gi' }
      }]
      scale: { minReplicas: 0, maxReplicas: 2 }
    }
  }
  dependsOn: [kvRole, acrPull]
}]

resource teamsApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${name}-teams'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: { external: true, targetPort: 3978, transport: 'auto' }
      registries: [{ server: acr.properties.loginServer, identity: identity.id }]
      secrets: secrets
    }
    template: {
      containers: [{
        name: 'teams'
        image: image
        command: ['cpokit', 'serve-teams']
        env: concat(commonEnv, [{ name: 'CLIENT_ID', value: botAppId }, { name: 'TENANT_ID', value: tenantId }])
        resources: { cpu: json('0.25'), memory: '0.5Gi' }
      }]
      scale: { minReplicas: 1, maxReplicas: 2 }
    }
  }
  dependsOn: [kvRole, acrPull]
}

resource bot 'Microsoft.BotService/botServices@2022-09-15' = {
  name: '${name}-bot'
  location: 'global'
  kind: 'azurebot'
  sku: { name: 'S1' }
  properties: {
    displayName: 'Back-office assistant'
    endpoint: 'https://${teamsApp.properties.configuration.ingress.fqdn}/api/messages'
    msaAppId: botAppId
    msaAppType: 'SingleTenant'
    msaAppTenantId: tenantId
    developerAppInsightKey: insights.properties.InstrumentationKey
  }
}

resource teams 'Microsoft.BotService/botServices/channels@2022-09-15' = {
  parent: bot
  name: 'MsTeamsChannel'
  location: 'global'
  properties: { channelName: 'MsTeamsChannel', properties: { isEnabled: true } }
}

resource budget 'Microsoft.Consumption/budgets@2023-11-01' = if (!empty(alertEmails)) {
  name: '${name}-budget'
  properties: {
    category: 'Cost'
    amount: monthlyBudgetEur
    timeGrain: 'Monthly'
    timePeriod: { startDate: budgetStart }
    notifications: {
      actual80: { enabled: true, operator: 'GreaterThan', threshold: 80, contactEmails: alertEmails }
      forecast100: { enabled: true, operator: 'GreaterThan', threshold: 100, thresholdType: 'Forecasted', contactEmails: alertEmails }
    }
  }
}

output apiUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
output foundryEndpoint string = foundry.properties.endpoint
output acrLoginServer string = acr.properties.loginServer
output apiAudience string = apiAudience
