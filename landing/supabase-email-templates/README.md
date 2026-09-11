# Supabase Auth email templates

Copy-paste these into **Supabase Dashboard → Authentication → Email Templates**.

| Template | Subject file | Body file |
| --- | --- | --- |
| Confirm signup | `confirm-signup.subject.txt` | `confirm-signup.html` |
| Reset password | `reset-password.subject.txt` | `reset-password.html` |
| Invite user | `invite-user.subject.txt` | `invite-user.html` |

Use `{{ .ConfirmationURL }}` as the button href (Supabase replaces it with the real link).

After editing templates, send a test signup from the local app to verify the subject line includes **BAKLOG** and links land on `https://baklog.app/auth/confirmed` or `/auth/reset`.
