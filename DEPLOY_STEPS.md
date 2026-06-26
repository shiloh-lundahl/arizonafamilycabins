# Deploy Checklist — Do These Steps In Order

Claude will do everything else. You just need to complete these 8 steps (most are just clicking things on websites).

---

## STEP 1 — Create a GitHub Account (if you don't have one)
1. Go to **github.com**
2. Click **Sign up**, use your email, create a password
3. Verify your email

---

## STEP 2 — Create a New GitHub Repo
1. Go to **github.com/new**
2. Repository name: `arizonafamilycabins`
3. Keep it **Public** (required for Render free)
4. Do NOT check "Add README"
5. Click **Create repository**
6. On the next screen, copy the URL that looks like: `https://github.com/YOURUSERNAME/arizonafamilycabins.git`

---

## STEP 3 — Connect and Push (run this in Terminal)
Replace `YOURUSERNAME` with your actual GitHub username:
```
cd "/Users/shilohlundahl/Main Operating Frame/arizonafamilycabins"
git remote add origin https://github.com/YOURUSERNAME/arizonafamilycabins.git
git push -u origin main
```
It will ask for your GitHub username and password. For password, use a **Personal Access Token**:
- Go to: github.com → Settings → Developer Settings → Personal access tokens → Tokens (classic) → Generate new token
- Check "repo", set expiration to 1 year, click Generate
- Copy the token — use it as your "password" when prompted

---

## STEP 4 — Create a Free Render Account
1. Go to **render.com**
2. Sign up with GitHub (click "Sign up with GitHub") — this connects them automatically
3. Authorize Render to access your GitHub

---

## STEP 5 — Deploy on Render
1. In Render dashboard, click **New → Web Service**
2. Select the `arizonafamilycabins` repo
3. Render will detect the `render.yaml` file automatically
4. Click **Deploy** — wait about 3 minutes
5. Your site will be live at `https://arizonafamilycabins.onrender.com`

---

## STEP 6 — Add Your Phone Number in Render
1. In Render, go to your web service → **Environment** tab
2. Find `PHONE_NUMBER` and enter your actual number, e.g. `(480) 555-0100`
3. Click Save → Render will redeploy automatically

---

## STEP 7 — Load the Content (do this ONCE)
After the site is live, open this URL in your browser (replace the service name):
```
https://arizonafamilycabins.onrender.com/admin/load-content-XK9mP2vQ7/
```
You should see JSON like `{"pages_loaded": 7, "articles_loaded": 0, "status": "ok"}`
Tell Claude you did this and Claude will remove the route.

---

## STEP 8 — Set Up HubSpot Free CRM
1. Go to **hubspot.com** → Sign up free (no credit card)
2. Go to Settings → Integrations → Private Apps → Create private app
3. Name it "Arizona Family Cabins", check "crm.objects.contacts.write"
4. Copy the token
5. In Render → Environment → add `HUBSPOT_API_KEY` → paste the token → Save

---

## STEP 9 (later) — Point Your Bluehost Domain
Tell Claude when you're ready to do this step and Claude will walk you through it.

---

## STEP 10 (later) — Google Search Console
Tell Claude when the domain is live and Claude will set up Search Console.

---

**Questions?** Just tell Claude what step you're on and what you're seeing.
