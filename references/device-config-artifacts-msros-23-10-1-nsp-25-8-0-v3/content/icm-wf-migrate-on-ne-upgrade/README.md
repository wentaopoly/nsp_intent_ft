# ICM Deployment Migration on NE Upgrade

## Description

When a Network Element (NE) is upgraded to a new NE release, you can migrate the NE configuration to a template which has been created from newer version of the intent-type.

For example, if an NE's software is upgraded from 22.10.R1 to 23.10.R1, and new configurable attributes are available in the newer version, you can create a template with the new intent and migrate the deployments from older templates.

This artifact contains four workflows, each performing its own specified tasks once invoked by the main workflow. They are:
- **icm-wf-migrate-on-ne-upgrade-main**
- **icm-wf-migrate-on-ne-upgrade-do-template-validation**
- **icm-wf-migrate-on-ne-upgrade-do-ne-validation**
- **icm-wf-migrate-on-ne-upgrade-do-bf**

To perform the action, **icm-wf-migrate-on-ne-upgrade-main** should be executed.

## Input

The **icm-wf-migrate-on-ne-upgrade-main** takes the following inputs:
1. **NE-IDs**: Takes a list with single NE object from which the configurations are to be migrated.
2. **List of Source and Target Template Pairs**:
   - **Source Template**: The template from which deployments on the specified NE need to be migrated.
   - **Target Template**: The template to which deployments on the specified NE will be migrated from the source template.

#### Note
- Only the deployments in **Deployed Aligned** and **Deployed Misaligned** states will be migrated.
- Workflow execution will fail if multiple NEs are provided in NE-IDs list.
- The associated intent type of source templates should have the labels attribute in icm-descriptor file. A place holder (example: "label": "enabled") will be sufficient for the labels to be auto populated when a new deployment is created with the source template.
- The associated intent type of target templates should have the target-labels with the target NE information (example : "target-labels": {"product": "7450 ESS, 7750 SR, 7950 XRS"} ) in icm-descriptor file.