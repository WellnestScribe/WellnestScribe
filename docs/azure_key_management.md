# WellNest Scribe — Azure Key Management & Encryption Setup

This document covers the entire lifecycle of the `FIELD_ENCRYPTION_KEY` — the key that
encrypts patient data (names, transcripts, SOAP notes) in the database.

---

## The Short Version

```
FIELD_ENCRYPTION_KEY not set  →  fields behave like normal text  (local dev, staging)
FIELD_ENCRYPTION_KEY set      →  all PHI fields encrypted at rest (production)
Key lost                      →  existing encrypted rows unreadable (gibberish on screen)
Key wrong                     →  same as lost — shows gAAAAAB... strings in the UI
```

---

## 1. Do You Need the Key Locally?

**No.** Local development does not need `FIELD_ENCRYPTION_KEY`.

Without it, `EncryptedTextField` and `EncryptedCharField` behave exactly like Django's
built-in `TextField` and `CharField`. The app works normally. New data is saved as
plaintext. This is intentional — local dev should use test data, not production PHI.

**Do not** copy your production key into your local `.env`. Keep them separate.

---

## 2. What Happens If the Key Is Lost?

This is the most important thing to understand.

| Scenario | What the app does |
|---|---|
| Key absent (not set) | New writes are plaintext. Old encrypted rows show as `gAAAAAB...` ciphertext strings in the UI. **No crash.** |
| Key wrong (typo or different key) | Same as absent — the decryption fails silently and shows ciphertext. **No crash.** |
| Key correct | Data encrypts on write, decrypts on read. Normal UI. |

**Recovery options if the key is lost:**
1. **Restore a database backup from before encryption was applied** — if Azure automatic backups are on (they are, by default on Flexible Server), you can restore to a point before `encrypt_existing_phi` was run.
2. **Recover the key from a password manager or secure note** — this is why you must back it up (see Section 4).
3. **No backup, no key recovery** — data in encrypted rows is permanently unreadable. This is the point of encryption; there is no backdoor.

**The key is not stored anywhere inside WellNest.** Not in the code, not in the database. Only you have it.

---

## 3. Generating the Key (One Time)

Run this command **once** on any machine with Python and the `cryptography` package:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Example output (yours will be different):
```
5K9M2X_example_key_do_not_use_this_one_XkP3QrBw4=
```

This is a 44-character URL-safe base64 string. It is a 256-bit symmetric key.

**Generate it only once for production.** If you generate a new key after data has been
encrypted with the old one, you will need to re-encrypt all existing rows with the new key
before discarding the old one.

---

## 4. Back Up the Key (Critical)

Before setting it anywhere, back it up in at least two of these:

| Option | How |
|---|---|
| **Password manager** (recommended) | 1Password, Bitwarden, LastPass — store as a secure note titled "WellNest Production Encryption Key" |
| **Azure Key Vault** (best practice) | See Section 7 — stores the key with access logs and rotation support |
| **Encrypted file** | `openssl enc -aes-256-cbc -pbkdf2 -in key.txt -out key.enc` — keep on a USB or external drive |

**Never:**
- Commit it to git (`.env` should be in `.gitignore` — check it is)
- Email it
- Store it in the database
- Share it via WhatsApp or messaging apps

---

## 5. Setting the Key on Azure App Service

### Option A — Azure Portal (easiest)

1. Go to **Azure Portal → Your App Service → Settings → Environment variables**
2. Click **+ Add**
3. Name: `FIELD_ENCRYPTION_KEY`
4. Value: *(paste the key you generated)*
5. Click **Apply → Save**
6. Azure will restart your app automatically

### Option B — Azure CLI

```bash
az webapp config appsettings set \
  --name YOUR_APP_SERVICE_NAME \
  --resource-group YOUR_RESOURCE_GROUP \
  --settings FIELD_ENCRYPTION_KEY="paste-your-key-here"
```

Replace `YOUR_APP_SERVICE_NAME` and `YOUR_RESOURCE_GROUP` with your actual values.

### Option C — Add to the existing JSON config

If you're managing settings via JSON export/import (as shown in a previous session):

```json
{
  "name": "FIELD_ENCRYPTION_KEY",
  "value": "paste-your-key-here",
  "slotSetting": false
}
```

Add this entry to the array and re-import via the portal.

---

## 6. Encrypting Existing Rows (Run Once After Setting the Key)

After the key is live on Azure and the app has restarted, SSH into the App Service
(or use the Kudu console) and run:

```bash
python manage.py encrypt_existing_phi
```

### Using the Kudu Console on Azure

1. Go to **Azure Portal → Your App Service → Development Tools → Advanced Tools → Go**
2. In Kudu, click **Debug console → CMD** (or **Bash** if available)
3. Navigate to your app directory: `cd site\wwwroot`
4. Run: `python manage.py encrypt_existing_phi`

### What the command does

- Reads every `ScribeSession` row through the ORM (which decrypts or passes through plaintext)
- Re-saves the PHI fields (which encrypts them with the current key)
- Does the same for every `SOAPNote`
- Safe to run multiple times — already-encrypted rows are decrypted then re-encrypted

### Expected output

```
Encrypting 42 ScribeSession rows …
  Sessions: 42 encrypted, 0 errors
Encrypting 38 SOAPNote rows …
  Notes:    38 encrypted, 0 errors
Done.
```

If you see errors, check `logs/wellnest.log` for the specific row PKs that failed.

---

## 7. Azure Key Vault (Recommended for Production)

Azure Key Vault is the professional way to manage this key. Instead of storing the key
directly in App Service config, you store it in Key Vault and grant the App Service a
managed identity to read it.

### Setup steps (overview)

```bash
# 1. Create a Key Vault (if you don't have one)
az keyvault create \
  --name wellnest-keyvault \
  --resource-group YOUR_RESOURCE_GROUP \
  --location eastus

# 2. Store the key
az keyvault secret set \
  --vault-name wellnest-keyvault \
  --name FieldEncryptionKey \
  --value "paste-your-key-here"

# 3. Enable managed identity on the App Service
az webapp identity assign \
  --name YOUR_APP_SERVICE_NAME \
  --resource-group YOUR_RESOURCE_GROUP

# 4. Grant the App Service read access to the secret
az keyvault set-policy \
  --name wellnest-keyvault \
  --object-id $(az webapp identity show --name YOUR_APP_SERVICE_NAME --resource-group YOUR_RESOURCE_GROUP --query principalId -o tsv) \
  --secret-permissions get
```

Then in App Service config, set:
```
FIELD_ENCRYPTION_KEY=@Microsoft.KeyVault(VaultName=wellnest-keyvault;SecretName=FieldEncryptionKey)
```

Azure automatically resolves this reference at runtime — the key is never stored in App
Service config in plaintext.

**Benefits of Key Vault:**
- Every access to the key is logged (audit trail)
- Key rotation without changing App Service config
- You can revoke access instantly if the App Service is compromised
- Keys are backed up automatically by Azure

---

## 8. Local Development (No Key Needed)

In your local `.env`:

```env
# Do NOT set FIELD_ENCRYPTION_KEY locally.
# Fields will work as plain text — correct for local dev with test data.
# FIELD_ENCRYPTION_KEY=  ← leave this absent or empty
```

If you previously ran `encrypt_existing_phi` on your local database and then removed the
key, you'll see ciphertext strings. To fix: either set the key again, or wipe and
reseed the local database (`python manage.py flush`).

---

## 9. Key Rotation (Future Procedure)

When you need to rotate the key (e.g., a team member who knew the key leaves):

1. Generate a new key (Section 3).
2. Set `FIELD_ENCRYPTION_KEY_PREVIOUS` to the old key value in App Service config.
3. Set `FIELD_ENCRYPTION_KEY` to the new key value.
4. Run `python manage.py encrypt_existing_phi` — this re-encrypts all rows with the new key.
   *(The management command reads with the old key via the fallback and writes with the new key.)*

> **Note:** The `FIELD_ENCRYPTION_KEY_PREVIOUS` support and the management command's
> two-key rotation mode are on the security TODO list (`docs/security.md`).
> For now, the manual rotation procedure is:
> (a) export a DB backup, (b) swap the key, (c) re-run `encrypt_existing_phi`.

5. Remove `FIELD_ENCRYPTION_KEY_PREVIOUS` from App Service config.
6. Revoke the old key in Key Vault (if using Key Vault).

---

## 10. Verifying Encryption Is Active

After setting the key and running `encrypt_existing_phi`, verify:

```bash
# Connect to the database and check a patient_name column directly
# (Using MySQL as an example)
mysql -h YOUR_DB_HOST -u YOUR_DB_USER -p YOUR_DB_NAME \
  -e "SELECT patient_name FROM scribe_scribesession LIMIT 3;"
```

If encryption is working you will see output like:

```
+------------------------------------------------------------------+
| patient_name                                                     |
+------------------------------------------------------------------+
| gAAAAABn8Kx2hJmP...long base64 string...==                      |
| gAAAAABn8Kx3iKnQ...long base64 string...==                      |
|                                                                  |
+------------------------------------------------------------------+
```

If you see plaintext names, the key is not set or `encrypt_existing_phi` has not been run.

---

## 11. Quick Reference Checklist

For a fresh Azure production deployment:

- [ ] Generate the key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- [ ] Save the key in your password manager
- [ ] Set `FIELD_ENCRYPTION_KEY` in Azure App Service Application Settings
- [ ] Set `SECURITY_ALERT_EMAIL` in Azure App Service Application Settings (for intrusion alerts)
- [ ] Wait for the app to restart
- [ ] SSH/Kudu into the App Service and run `python manage.py encrypt_existing_phi`
- [ ] Verify by querying the database directly (Section 10)
- [ ] (Optional but recommended) Move the key to Azure Key Vault (Section 7)

---

## 12. Environment Variable Reference

| Variable | Required for encryption | Description |
|---|---|---|
| `FIELD_ENCRYPTION_KEY` | Yes | Fernet key for PHI field encryption. Absent = plaintext fallback (safe for dev). |
| `SECURITY_ALERT_EMAIL` | No | Email address for intrusion detection alerts. |
| `IDLE_LOCK_MINUTES` | No | Idle lock timeout in minutes. Default: 15. |
| `AUTO_DELETE_AUDIO_DAYS` | No | Days before audio files are auto-purged. Default: 30. |
