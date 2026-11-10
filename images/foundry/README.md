# Foundry Windows image

This image is built from Windows Server 2022 Datacenter Azure Edition and
published to the existing private `galLabForge` Compute Gallery. The image
definition is `img-foundry`. Gallery versions are immutable, so each build
requires a new version. Versions `1.0.0` and `1.0.1` failed VM OS-provisioning
acceptance and must not be used for learner VMs.

## Prerequisites

- Packer 1.10 or later with the HashiCorp Azure plugin.
- Azure CLI signed in to the intended subscription.
- `rg-labforge-core` and `galLabForge` deployed in Central India.
- The selected temporary builder SKU, defaulting to `Standard_B2s`, available
  in the region and sufficient family and
  regional vCPU quota.
- Cost approval for the temporary image-builder resources.

The Packer build creates temporary Azure resources and may incur charges.
Review its plan and costs before running it. Packer's temporary image-builder
VM is separate from learner lab VMs; learner VMs must remain private-only.

## Create the image definition

```powershell
az deployment group create `
  --resource-group rg-labforge-core `
  --template-file images/foundry/image-definition.bicep
```

## Build and publish

```powershell
$env:AZURE_SUBSCRIPTION_ID = (az account show --query id --output tsv)
$env:IMAGE_VERSION = "1.0.2"
$env:LABFORGE_SESSION_ID = "foundry-image-build-001"
packer init images/foundry/foundry.pkr.hcl
packer validate `
  -var "subscription_id=$env:AZURE_SUBSCRIPTION_ID" `
  -var "image_version=$env:IMAGE_VERSION" `
  -var "session_id=$env:LABFORGE_SESSION_ID" `
  images/foundry/foundry.pkr.hcl
packer build `
  -var "subscription_id=$env:AZURE_SUBSCRIPTION_ID" `
  -var "image_version=$env:IMAGE_VERSION" `
  -var "session_id=$env:LABFORGE_SESSION_ID" `
  images/foundry/foundry.pkr.hcl
```

The final provisioner runs Sysprep and waits for Windows to report the
generalized image state before Packer captures it. Temporary resources and the
gallery version are tagged with `LABFORGE_SESSION_ID`. The public desktop
shortcut passes the shared extensions directory to VS Code so the learner
account loads the pre-installed extensions. Never put credentials in the
template; authentication uses the Azure CLI session.

## Verify the published version

```powershell
az sig image-version show `
  --resource-group rg-labforge-core `
  --gallery-name galLabForge `
  --gallery-image-definition img-foundry `
  --gallery-image-version $env:IMAGE_VERSION `
  --query provisioningState `
  --output tsv
```

Only update the course manifest after a private-only test VM has completed OS
provisioning and the installed tools have been verified.
