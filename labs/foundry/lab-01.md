# Prepare your Foundry development environment

## Goals

- Confirm the lab image tools are available to your learner account.
- Create a workspace for the course exercises.

## Check the installed tools

Open the **LabForge Labs** desktop shortcut and open a new terminal in VS Code.

- [ ] Run `python --version` and confirm Python 3.12 is available.
- [ ] Run `git --version`.
- [ ] Run `az version`.
- [ ] Run `code --list-extensions` and confirm the Python, Jupyter, and Microsoft Foundry Toolkit extensions are listed.

---page---

## Create your lab workspace

- [ ] Create a folder named `lab1` under `C:\Labs`.
- [ ] Open the folder in VS Code.
- [ ] Create a `README.md` file describing what you want to build.
- [ ] Initialize Git and create the first commit.

```powershell
Set-Location C:\Labs\lab1
git init
Set-Content README.md "# My Foundry lab"
git add README.md
git commit -m "Create lab workspace"
```

> **Note:** Azure sign-in and Foundry resource creation depend on your course
> account and the permissions provided for this session.
