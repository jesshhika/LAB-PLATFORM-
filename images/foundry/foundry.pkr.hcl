packer {
  required_plugins {
    azure = {
      source  = "github.com/hashicorp/azure"
      version = ">= 2.0.0"
    }
  }
}

variable "subscription_id" {
  type        = string
  description = "Subscription containing the LabForge resource groups."
  default     = env("AZURE_SUBSCRIPTION_ID")
}

variable "location" {
  type        = string
  description = "Azure region for the build and image version."
  default     = "centralindia"
}

variable "resource_group_name" {
  type        = string
  description = "Resource group containing the private Compute Gallery."
  default     = "rg-labforge-core"
}

variable "gallery_name" {
  type    = string
  default = "galLabForge"
}

variable "image_definition" {
  type    = string
  default = "img-foundry"
}

variable "image_version" {
  type        = string
  description = "New, unused immutable version to publish to the Compute Gallery."
}

variable "session_id" {
  type        = string
  description = "Session ID applied to temporary image-builder resources."
}

variable "vm_size" {
  type        = string
  description = "Temporary image-builder VM size."
  default     = "Standard_B2s"
}

source "azure-arm" "foundry-windows" {
  use_azure_cli_auth = true
  subscription_id    = var.subscription_id
  location           = var.location
  os_type            = "Windows"
  vm_size            = var.vm_size

  image_publisher = "MicrosoftWindowsServer"
  image_offer     = "WindowsServer"
  image_sku       = "2022-datacenter-azure-edition"
  image_version   = "latest"

  azure_tags = {
    labforge   = "true"
    purpose    = "foundry-image-rebuild"
    session_id = var.session_id
  }

  communicator   = "winrm"
  winrm_username = "packer"
  winrm_timeout  = "2h"
  winrm_use_ssl  = true
  winrm_insecure = true

  shared_image_gallery_destination {
    subscription         = var.subscription_id
    resource_group       = var.resource_group_name
    gallery_name         = var.gallery_name
    image_name           = var.image_definition
    image_version        = var.image_version
    replication_regions  = [var.location]
    storage_account_type = "Standard_LRS"
  }
}

build {
  name    = "labforge-foundry-windows"
  sources = ["source.azure-arm.foundry-windows"]

  provisioner "powershell" {
    script = "${path.root}/install.ps1"
  }

  provisioner "powershell" {
    inline = [
      "if (Test-Path $Env:SystemRoot\\windows\\system32\\Sysprep\\unattend.xml) { Remove-Item $Env:SystemRoot\\windows\\system32\\Sysprep\\unattend.xml -Force -ErrorAction Stop }",
      "& $env:SystemRoot\\System32\\Sysprep\\Sysprep.exe /oobe /generalize /quiet /quit /mode:vm",
      "$deadline = (Get-Date).AddMinutes(10)",
      "do { $imageState = (Get-ItemProperty HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Setup\\State).ImageState; if ($imageState -eq 'IMAGE_STATE_GENERALIZE_RESEAL_TO_OOBE') { break }; Start-Sleep -Seconds 10 } while ((Get-Date) -lt $deadline)",
      "if ($imageState -ne 'IMAGE_STATE_GENERALIZE_RESEAL_TO_OOBE') { throw \"Sysprep did not reach the expected image state; current state: $imageState\" }"
    ]
  }
}
