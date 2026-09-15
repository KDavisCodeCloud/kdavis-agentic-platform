import type { BlogPost } from '../types'

import { post as terraformDriftDetection } from './terraform-drift-detection'
import { post as cloudMisconfigurationDetection } from './cloud-misconfiguration-detection'
import { post as reduceMttrCloudInfrastructure } from './reduce-mttr-cloud-infrastructure'
import { post as terraformApplyFailedDiagnosis } from './terraform-apply-failed-diagnosis'
import { post as azureNsgMisconfiguration } from './azure-nsg-misconfiguration'
import { post as awsIamMisconfiguration } from './aws-iam-misconfiguration'
import { post as betterOnCallIncidentResponse } from './better-on-call-incident-response'
import { post as iacDriftTerraformBicepArmCloudformation } from './iac-drift-terraform-bicep-arm-cloudformation'
import { post as cloudMisconfigurationComplianceFindings } from './cloud-misconfiguration-compliance-findings'
import { post as multiCloudInfrastructureMonitoring } from './multi-cloud-infrastructure-monitoring'

// Publish dates are staggered on purpose (see each post's publishedDate) --
// week 1: posts 1 & 4, week 2: posts 2 & 6, week 3: posts 3 & 7,
// week 4: posts 5 & 9, week 5: posts 8 & 10 -- so search engines see
// regular fresh content instead of a single 10-post dump.
export const ALL_POSTS: BlogPost[] = [
  terraformDriftDetection,
  cloudMisconfigurationDetection,
  reduceMttrCloudInfrastructure,
  terraformApplyFailedDiagnosis,
  azureNsgMisconfiguration,
  awsIamMisconfiguration,
  betterOnCallIncidentResponse,
  iacDriftTerraformBicepArmCloudformation,
  cloudMisconfigurationComplianceFindings,
  multiCloudInfrastructureMonitoring,
]
