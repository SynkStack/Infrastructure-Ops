# Rollback Procedure

This runbook returns an environment to its last known good release and configuration. It is written for a small team: one person leads (the **Deploy Lead**), and one other person checks each step (the **Reviewer**). Commands are PowerShell, with Bash differences noted.

## When rollback is required

Roll back, rather than debug in place, when a deployment has been made and any of these is true:

- Post-deployment verification fails after all retries (see [deployment.md](deployment.md#post-deployment-verification)).
- A core user flow is broken and the cause is not understood within 15 minutes.
- Errors or failed requests are clearly higher than before the deployment.
- Configuration was deployed incorrectly (wrong environment values, wrong URL) and cannot be corrected quickly.
- A secret or sensitive value was exposed. Roll back **and** rotate the secret (see [Configuration rollback](#configuration-rollback)).

## Decision criteria

The Deploy Lead decides. If unavailable, the Reviewer decides. Use this table:

| Situation | Decision |
|---|---|
| Health check fails after retries in production | **Roll back** |
| Core flow broken and cause unknown after 15 minutes | **Roll back** |
| Data or secrets exposed | **Roll back immediately**, then rotate secrets |
| Minor visual or non-critical defect, workaround exists | Fix forward through a normal pull request |
| Fix is one small, already understood change and can be deployed and verified within 30 minutes | Fix forward, with a second approval |
| Staging only is affected | Redeploy the previous staging tag. Production is untouched. A full incident record is not required |

Time-box every incident: if the situation is not improving within 15 minutes of detection, roll back. When in doubt, roll back. A rollback can be undone by deploying again, but extended downtime cannot be undone.

## Rollback procedure

Time estimate: 15 to 30 minutes.

1. **Declare it.** The Deploy Lead tells the team: "Rolling back `<environment>` from `<tag>`." Pause other deployments.
2. **Find the last known good tag:**

   ```powershell
   git fetch --tags
   git tag --list "production-*" --sort=-creatordate
   ```

   The newest tag is the failed deployment. The one below it is the last known good unless the release notes say it was also bad. Write both tags down.

3. **Redeploy the previous application release** for that tag, using the same mechanism used for deployments (step 4 of the [deployment steps](deployment.md#deployment-steps)).
4. **Restore configuration** if configuration changed between the two tags (see next section).
5. **Verify** the environment:

   ```powershell
   python scripts/verify_deployment.py --environment production --retries 6 --interval 10
   ```

6. **Run the manual smoke test** from the deployment guide.
7. **Tag the rollback** so history shows the environment's current state. Use the next number for the day and say what it is:

   ```powershell
   git tag -a production-20261116-2 -m "Rollback to production-20261109-1, failure in production-20261116-1"
   git push origin production-20261116-2
   ```

8. **Announce completion** to the team with the tag, the time, and the verification result.

## Configuration rollback

Compare configuration between the failed tag and the last known good tag:

```powershell
git diff production-20261109-1 production-20261116-1 -- config/production
```

If there is no difference, skip to verification. Otherwise restore the previous configuration:

```powershell
git checkout main
git pull
git checkout -b revert/production-config-20261116
git checkout production-20261109-1 -- config/production
python scripts/validate_config.py
git commit -am "revert: restore production config from production-20261109-1"
git push -u origin revert/production-config-20261116
```

Open a pull request. CI must pass. Because this is an incident, one approval is enough and the Reviewer should approve promptly. (To undo one specific bad commit instead, use `git revert <commit>` and push the same way.)

**Secret values** are not in Git. If the previous release needs previous secret values, restore them from the team's secret store, then re-run:

```powershell
python scripts/validate_config.py --runtime-env production --env-file "$HOME\opssynk-secrets\production.env"
```

If a secret may have been exposed, generate a new one and replace it everywhere it is used rather than restoring the old value.

## Recovery checklist

Copy this into the incident issue and tick each item:

- [ ] Rollback declared and the team informed
- [ ] Failed tag and last known good tag recorded
- [ ] Previous application release redeployed
- [ ] Configuration compared, and restored if it differed
- [ ] `verify_deployment.py` passed
- [ ] Manual smoke test passed
- [ ] Rollback tag created and pushed
- [ ] Configuration revert pull request opened (if configuration was restored)
- [ ] Secrets rotated (if exposure was suspected)
- [ ] Team informed that the rollback is complete
- [ ] Post-rollback note written (below)

## Post-rollback documentation

Within one working day, open a GitHub issue titled `Incident: <environment> rollback <YYYY-MM-DD>` and fill in this note:

```text
Environment:        production | staging
Detected at:        <date and time, timezone>
Rolled back at:     <date and time, timezone>
Failed release:     <tag> (app release <version>)
Restored release:   <tag> (app release <version>)
Detected by:        <person or check>
Impact:             <what users saw and for how long>
Root cause:         <known cause, or "under investigation">
Configuration:      <changed or unchanged, link to revert PR>
What went well:     <short>
What to improve:    <short>
Follow-up actions:  <issue links, each with an owner>
```

Do not redeploy the failed release until the root cause is understood, the fix has passed CI and staging, and the Deploy Lead has approved. If a step in this runbook was wrong or unclear, fix this document in the same follow-up.
