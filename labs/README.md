# Labs

Each course directory contains a `course.yaml` manifest, Markdown guides, and
learner-facing assets. The API loads manifests from this directory and resolves
each guide path relative to its course folder.

Guides support `---page---` separators, GitHub task-list checkboxes, and
session placeholders such as `{{vm.username}}` and `{{azure.resourceGroup}}`.
Use blockquotes for notes and warnings. VM validation scripts are referenced
from the course manifest and run through Azure VM Run Command.

The Foundry course manifest is pinned to `img-foundry:1.0.0`. Versions `1.0.0`
and `1.0.1` failed Azure OS-provisioning acceptance; do not use either for
learner sessions. Update the manifest only after a new image version passes
private-VM provisioning and tool validation.
