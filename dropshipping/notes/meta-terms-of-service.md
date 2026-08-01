# Meta Terms of Service — agent knowledge

**Official source (always authoritative):**  
https://www.facebook.com/legal/terms  

**Documented for ShopifyDS agents:** 2026-07-29  
**Effective (as published):** January 1, 2025  
**Provider:** Meta Platforms, Inc.  
**Store context:** Basecamp and Backwoods ads, Page, pixel, Marketing API — see `marketing-plan.md`, `notes/meta-marketing-api-setup-2026-07-28.md`, `notes/meta-budgets-spending-limits.md`.

This file is a **working summary for agents**, not legal advice and not a substitute for the full Terms. When in doubt, open the official URL and defer to **human** for legal/compliance decisions.

---

## What these Terms cover

- Govern access/use of **Facebook, Messenger**, and other **Meta Products** (except where separate terms apply, e.g. Instagram Terms of Use).
- Agreement is with **Meta Platforms, Inc.**
- If you disagree → do not access/use covered Products.
- These Terms supersede prior agreements about use of the Products.

**Free consumer use is funded by ads:** Meta does not charge end users for most consumer Products; businesses pay to show ads. By using Products, users agree Meta can show personalized ads. Meta states it does **not sell** personal data to advertisers and does not share direct identifiers (name, email, etc.) with advertisers unless the user gives specific permission.

Related: [Privacy Policy](https://www.facebook.com/privacy/policy/) · [Meta Products list](https://facebook.com/legal/meta-products)

---

## Services Meta provides (high level — §1)

Personalization; connecting people/orgs; expression/communication; discovery of content/products/services (including **personalized ads**); safety/security/integrity; advanced tech (AI/ML/AR); research; consistent experiences across Meta Company Products; global infrastructure/data transfer.

**Agent relevance:** Ad delivery, Page presence, and measurement all sit inside this product ecosystem. Account/Page integrity and policy violations can lead to content removal or account disablement.

---

## How ads are funded (§2) — important for store ads

- Businesses/orgs pay Meta to show **personalized ads** and sponsored content.
- Advertisers describe **goals and audiences** (e.g. age/interest); Meta shows ads to people it thinks may be interested.
- Advertisers get **performance reports** and general demo/interest aggregates — **not** direct personal identifiers unless user permission.
- Users have controls over ad types / data used for ads.

**Agent rules:**

- Do not claim Meta “gives us customer emails/names from the pixel” as a default.
- Use audiences and reporting as designed (Aggregated/Insights); do not try to re-identify users.
- Pixel + Marketing API work must stay within platform + privacy expectations.

---

## Commitments that matter for agents (§3)

### Account authenticity (§3.1)

Users must provide real everyday name, accurate info, one personal account, not share passwords / transfer accounts without permission.

You **cannot** use Facebook if under 13, convicted sex offender, previously disabled for ToS/Community Standards violations (without Meta permission), or prohibited by law.

**Agent rules:**

- Do **not** create fake personal profiles to run the brand.
- Brand presence = **Facebook Page** + Business Manager + ad account (commercial use).
- Do **not** share, paste, or commit passwords or access tokens in git/STATUS/chat logs.

### What you may not do (§3.2) — high risk for automation

You may not use Products to do/share anything that:

- Violates Terms, [Community Standards](https://transparency.meta.com/policies/community-standards/), or other applicable policies  
- Is **unlawful, misleading, discriminatory, or fraudulent**  
- You lack rights to share  
- Infringes IP (copyright, trademark, **counterfeit/pirated goods**)  

Also prohibited (summary):

- Malware, spam, overload/impair services  
- **Automated data collection** without Meta permission ([Automated Data Collection Terms](https://www.facebook.com/legal/automated_data_collection_terms))  
- Proxy/request/collect usernames/passwords or **misappropriate access tokens**  
- Sell/license/purchase data obtained from Meta (except as Platform Terms allow)  
- Misuse reporting/appeals channels  
- Circumvent technical access controls  

Meta may remove content and suspend/disable accounts for violations.

**Agent rules for Basecamp ads/catalog:**

- Ad copy and creatives must be **truthful** (shipping times, product claims, discounts).  
- Do not advertise **counterfeit** or rights-violating goods.  
- Do not scrape Graph/HTML outside allowed API + token scopes.  
- Do not harvest or resell Meta user data.  
- Prefer official **Marketing API / Ads Manager / Business tools** with stored tokens under `~\.meta-link\` only.

### Permissions you grant Meta (§3.3)

- You keep IP in content you create; you grant Meta a broad **license** to host/use/distribute content to run the Products (consistent with privacy/app settings).  
- License ends when content is deleted from their systems (with retention exceptions).  
- Permission to use name/profile picture/actions with ads in limited ways (user-facing social context).  
- Software update permission when apps are installed.

**Agent takeaway:** Creatives uploaded for ads are used by Meta to deliver those ads under their systems; keep brand assets rights-clear (our photos/video or licensed).

### Meta IP (§3.4)

Do not misuse Meta trademarks/brand assets except per Brand Usage Guidelines or written permission. No reverse engineering except limited legal/bug-bounty cases.

---

## Enforcement & risk (§4)

| Topic | Summary | Agent takeaway |
|-------|---------|----------------|
| **Updates** | Meta may update Terms; continued use = acceptance | Re-check official URL if policies change mid-campaign |
| **Suspension** | Clear/serious/repeated breaches → suspend/disable access or delete account; also IP repeat infringement / legal requirements | Policy-breaking ads or deceptive practices can kill the ad account — escalate to human |
| **Liability** | Products “as is”; broad liability limits under applicable law | Do not promise guaranteed delivery, ROAS, or uninterrupted ads |
| **Disputes** | CA courts / California law (with Meta option to sue in user country) | Legal disputes are **human-only** |
| **Commercial use** | Using Products for **business** (ads, selling, Page for business, measurement, apps) → also **[Commercial Terms](https://www.facebook.com/legal/commercial_terms)** | Our store **must** treat Commercial Terms + ad policies as binding for ads work |

---

## Other policies agents should know (§5)

When doing ads / Page / commerce for Basecamp, these often apply **in addition** to the main Terms:

| Policy | URL | When |
|--------|-----|------|
| **Commercial Terms** | https://www.facebook.com/legal/commercial_terms | Any commercial/business use (ads, Page, selling, measurement) |
| **Advertising Policies / Ad Standards** | https://transparency.meta.com/policies/ad-standards/ | What ad content is allowed — team summary: `notes/meta-ad-standards.md` |
| **Self-Serve Ad Terms** | https://www.facebook.com/legal/self_service_ads_terms | Creating/submitting ads via self-serve tools / APIs |
| **Pages, Groups and Events Policy** | https://www.facebook.com/policies/pages_groups_events | Creating/admin of brand **Page** |
| **Commerce Policies** | https://www.facebook.com/policies/commerce | Offering products for sale on Meta surfaces |
| **Community Payment Terms** | https://www.facebook.com/payments_terms | Payments on Meta Products |
| **Community Standards** | https://www.facebook.com/communitystandards | Content/activity standards |
| **Platform Policy** | https://developers.facebook.com/policy/ | Marketing API / Platform use |
| **Meta AI Terms** | https://www.facebook.com/legal/ai-terms | Generative AI products/features |
| **Music Guidelines** | https://www.facebook.com/legal/music_guidelines | Music in creatives |

**Budget vocabulary (separate help doc):** `notes/meta-budgets-spending-limits.md`

---

## ShopifyDS agent checklist (actionable)

1. **Authority:** Full text lives at https://www.facebook.com/legal/terms — this note is a summary only.  
2. **Business path:** Ads + brand Page = **Commercial Terms** + **Ad Standards** + **Self-Serve Ad Terms** + **Pages policy**, not “personal account only.”  
3. **No deception:** Misleading claims, fake scarcity, wrong shipping promises → policy risk. Align PDP + ads.  
4. **No counterfeits / IP theft** in catalog or creatives.  
5. **No token abuse:** Never misappropriate, share, or commit access tokens; store only under `~\.meta-link\`.  
6. **No unauthorized scraping** of Meta data; use approved APIs and scopes.  
7. **Privacy:** Do not attempt to re-identify users from ad reports or pixel aggregates.  
8. **Enforcement:** If Meta restricts the ad account, Page, or pixel — **stop**, document in STATUS, **notify human**; do not create workaround accounts.  
9. **Spend still capped** by plan ($25/wk) and `MISSION.md` profit policy; ToS does not authorize overspend.  
10. **Human-only:** Accepting new legal agreements that require human checkbox, payment method changes, identity verification, Page creation under a personal identity, legal disputes.

---

## Related team docs

| Doc | Role |
|-----|------|
| `notes/meta-marketing-api-setup-2026-07-28.md` | Token, ad account, Page blocker |
| `notes/meta-budgets-spending-limits.md` | Budget vs threshold |
| `notes/meta-ad-standards.md` | Ad Standards summary (Transparency Center) |
| `notes/meta-lead-ad-terms.md` | Lead Ad / lead-gen ToS |
| `marketing-plan.md` | Week 1 spend + creatives |
| `MISSION.md` | CX / revenue / profit→budget |
| `AGENTS.md` | Unattended checklist |
