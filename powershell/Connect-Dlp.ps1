#Requires -Version 5.1
<#
.SYNOPSIS
    Prepares the app certificate for Microsoft365DSC app-only auth (READ-ONLY recon).

    Runs under Windows PowerShell 5.1 (required by Microsoft365DSC's DSC resources).

.DESCRIPTION
    Retrieves the certificate from Key Vault via the Azure CLI, loads it as an
    X509Certificate2, and registers it in the CurrentUser\My store so that
    Export-M365DSCConfiguration can find it by thumbprint and open its own app-only
    Security & Compliance connection.

    Azure CLI (a separate process) is used deliberately instead of the Az PowerShell
    module: importing Az into this Windows PowerShell 5.1 session loads
    Microsoft.IdentityModel assemblies that collide with ExchangeOnlineManagement and
    break the Security & Compliance connection with error IDX12729.

    Dot-source this script so $env:DLP_CERT_THUMBPRINT stays available to
    Export-Dlp.ps1 in the same process:  . ./Connect-Dlp.ps1

.NOTES
    Read-only usage only. This script never calls New-/Set-/Remove-* cmdlets.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --- Validate required environment (supplied by the workflow as Variables) ---
$required = 'AZURE_CLIENT_ID', 'KEY_VAULT_NAME', 'CERT_NAME', 'M365_ORGANIZATION'
foreach ($name in $required) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
        throw "Required environment variable '$name' is not set."
    }
}

# --- Retrieve the certificate (PFX) from Key Vault via Azure CLI ---
# A certificate stored in Key Vault is retrievable via the secret endpoint as a
# base64-encoded, password-less PKCS#12 (PFX) blob that includes the private key.
Write-Host "Retrieving certificate '$env:CERT_NAME' from Key Vault '$env:KEY_VAULT_NAME' via Azure CLI..."
$pfxBase64 = az keyvault secret show --vault-name $env:KEY_VAULT_NAME --name $env:CERT_NAME --query value -o tsv
if ($LASTEXITCODE -ne 0) {
    throw "az keyvault secret show failed with exit code $LASTEXITCODE."
}
if ([string]::IsNullOrWhiteSpace($pfxBase64)) {
    throw "Key Vault returned an empty value for certificate '$env:CERT_NAME'."
}
$pfxBytes = [Convert]::FromBase64String($pfxBase64)

# The app-only certificate must be CSP (not CNG). Persist the key to the user store so
# it is available for signing; EphemeralKeySet is NOT compatible with CSP keys.
$flags = [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]'PersistKeySet,Exportable'
$cert = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($pfxBytes, [string]$null, $flags)
Write-Host "Loaded certificate. Thumbprint=$($cert.Thumbprint) HasPrivateKey=$($cert.HasPrivateKey)"
if (-not $cert.HasPrivateKey) {
    throw "Certificate '$env:CERT_NAME' was loaded without a private key; app-only auth cannot sign."
}

# --- Register the certificate so Microsoft365DSC can locate it by thumbprint ---
$store = [System.Security.Cryptography.X509Certificates.X509Store]::new('My', 'CurrentUser')
$store.Open('ReadWrite')
$store.Add($cert)
$store.Close()
$env:DLP_CERT_THUMBPRINT = $cert.Thumbprint

Write-Host "Certificate registered in CurrentUser\My. Microsoft365DSC will connect app-only using thumbprint $($cert.Thumbprint) for '$env:M365_ORGANIZATION'."
