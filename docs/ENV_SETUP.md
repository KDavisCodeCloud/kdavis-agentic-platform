# Environment Variable Setup Guide

## Before First Build Session

### Systeme.io
1. Log into systeme.io
2. Go to Settings → Automations → Tags
3. Create the following tags exactly:
   - cd-cold-seq-1
   - cd-trial-onboard
   - cd-trial-convert
   - cd-churn-save
   - cd-expansion
   - mse-cold-seq-1
   - mse-trial-onboard
   - mse-trial-convert
   - mse-churn-save
   - mse-expansion
4. Copy each tag ID from systeme.io
5. Paste into .env next to the matching variable

### Systeme.io API Key
1. Go to Settings → Public API keys
2. Click Generate new key
3. Leave expiration empty (permanent)
4. Copy key into SYSTEME_API_KEY in .env

### Apollo
1. Log into apollo.io
2. Go to Settings → Integrations → API
3. Generate API key
4. Copy into APOLLO_API_KEY in .env

### Adding New MSE Products
When a new MSE product launches add 5 new tags
to systeme.io and 5 new variables to .env:
  SYSTEME_TAG_{PRODUCT_CODE}_COLD_SEQ_1=
  SYSTEME_TAG_{PRODUCT_CODE}_TRIAL_ONBOARD=
  SYSTEME_TAG_{PRODUCT_CODE}_TRIAL_CONVERT=
  SYSTEME_TAG_{PRODUCT_CODE}_CHURN_SAVE=
  SYSTEME_TAG_{PRODUCT_CODE}_EXPANSION=

Then add a row to the campaigns table in Supabase
for each new tag. MKT-12 handles all enrollment
from that point forward automatically.
