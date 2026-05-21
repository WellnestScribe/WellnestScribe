# WellnestScribe + GNU Health — Local Dev Runbook

> Keep this file. Run these commands each time you want to start the stack.

---

## 1. Start WellnestScribe (do this every session)

Open **PowerShell** and run:

```powershell
cd "c:\xampp\htdocs\WellnestScribe"
.\.venv\Scripts\python.exe manage.py runserver 0.0.0.0:9093
```

Then open: **http://localhost:9093/**

Login with your existing account. Leave this terminal open — closing it stops the server.

> **Important:** Always use `http://localhost:9093/` in the browser. `http://0.0.0.0:9093/` will show `ERR_ADDRESS_INVALID`.

---

## 2. Start GNU Health (only needed when you want the external EMR)

Open a **second PowerShell window** and run:

```powershell
cd "c:\xampp\htdocs\WellnestScribe\gnuhealth"
docker compose up --build -d
```

- **First run**: builds the image (~5–10 min, downloads ~1 GB of Python packages)
- **Every run after**: starts in ~30 seconds (image is cached, use `docker compose up -d`)
- **Check it's up**: `docker compose ps` — both containers should show `running`

Status page: **http://localhost:8069/**  
Default login: `admin` / `change_me_before_deploy`

To stop: `docker compose down`  
To wipe all data and start fresh: `docker compose down -v`

---

## 3. Connect the Tryton Desktop Client to GNU Health

The Tryton desktop client gives you a full graphical UI for GNU Health (patients, appointments, lab, etc).

**Download:** https://www.tryton.org/download — install the Windows version.

### Connecting (Profile Editor)

When Tryton opens, the **Profile Editor** dialog appears. Fill it in exactly:

| Field | Value |
|-------|-------|
| **Host** | `localhost:8069` *(include the port — just `localhost` will fail)* |
| **Database** | `gnuhealth` |
| **Username** | `admin` |

Click the checkmark / Save, then **Log In**.  
Password: `change_me_before_deploy`

### "Could not connect to the server" fix

If you typed just `localhost` in the Host field, the client tries the wrong default port (8000). Always use `localhost:8069`.

If that still fails:
```powershell
cd "c:\xampp\htdocs\WellnestScribe\gnuhealth"
docker compose ps
```
Both `wellnest_gnuhealth_db` and `wellnest_gnuhealth` must be `running`. If not:
```powershell
docker compose up -d
docker compose logs gnuhealth --tail=30
```

### 401 / Authentication failed fix

If the client connects but authentication fails, the admin password may not have been set on first run. Fix it manually:

```powershell
# Step 1: open a shell inside the container
docker exec -it wellnest_gnuhealth bash

# Step 2: inside the container, set the password
PASS_FILE=$(mktemp)
echo "change_me_before_deploy" > $PASS_FILE
TRYTONPASSFILE=$PASS_FILE trytond-admin -c /etc/trytond.conf -d gnuhealth -p
rm -f $PASS_FILE
exit
```

Then retry connecting from the desktop client.

---

## 4. Switch WellnestScribe to use GNU Health as its EMR

Edit `.env` in the project root:

```
# Change this line:
EMR_BACKEND=local

# To:
EMR_BACKEND=gnuhealth
GNUHEALTH_PASSWORD=change_me_before_deploy
```

Then restart WellnestScribe (Ctrl+C and re-run). Verify the connection:

```
http://localhost:9093/emr/api/gnuhealth/status/
```

Should return `{"status": "connected", ...}`

> **Default is `EMR_BACKEND=local`** — WellnestScribe's built-in EMR works without Docker at all.

---

## 5. Push a Scribe session to GNU Health

Once GNU Health is running and `EMR_BACKEND=gnuhealth` is set:

1. Record + generate a note as normal
2. On the **Review page**, click **Push to GNU Health**
3. Search for the patient by name, or check "Create new patient"
4. Click Push — the encounter is created in GNU Health

### API endpoints (for direct testing)

```
GET  /emr/api/gnuhealth/status/
GET  /emr/api/gnuhealth/patients/?q=Smith
POST /emr/api/gnuhealth/sessions/<session-id>/push/
     Body: { "patient_id": "42" }
     or:   { "create_patient": true }
```

---

## 6. Daily startup checklist

```
[ ] PowerShell #1 → cd WellnestScribe → start Django (step 1)
[ ] (EMR testing) PowerShell #2 → cd gnuhealth → docker compose up -d
[ ] Open http://localhost:9093/ in browser
[ ] Login
```

---

## 7. Ports at a glance

| Service | Port | URL |
|---------|------|-----|
| WellnestScribe (Django) | 9093 | http://localhost:9093/ |
| GNU Health (Tryton XML-RPC + web) | 8069 | http://localhost:8069/ |
| GNU Health PostgreSQL | 5433 | `psql -h localhost -p 5433 -U gnuhealth gnuhealth` |

---

## 8. Troubleshooting

**`ERR_ADDRESS_INVALID` when opening the app**  
→ You typed `0.0.0.0:9093` in the browser. Use `localhost:9093` instead.

**Django says "No module named decouple"**  
→ You're using the system Python. Always use `.\.venv\Scripts\python.exe manage.py runserver …`

**Tryton: "Could not connect to the server"**  
→ Host field must be `localhost:8069`, not just `localhost`. Also confirm `docker compose ps` shows both containers running.

**Tryton: 401 / authentication failed**  
→ Admin password wasn't set on first run. See step 3 → "401 fix" above.

**GNU Health container keeps restarting**  
→ First run takes time. Watch logs: `docker compose logs -f gnuhealth`

**`upgrade returned non-zero` warning in logs**  
→ Harmless on restart when nothing changed. Only a problem if it happens on first run.

**`EMR_BACKEND=gnuhealth` but getting connection errors in WellnestScribe**  
→ Confirm `docker compose ps` shows `running` for both containers, then check `GNUHEALTH_PASSWORD` in `.env` matches what you set in the container.

**Mic level bar doesn't move**  
→ Click "Mic settings" on the record page and pick a different device. Hit "Test mic" to verify.
