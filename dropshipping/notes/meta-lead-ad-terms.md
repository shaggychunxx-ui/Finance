# Meta Lead Ad Terms — agent knowledge

**Official source (always authoritative):**  
https://www.facebook.com/legal/leadgen/tos  

**Documented for ShopifyDS agents:** 2026-07-29  
**Last modified (Meta):** October 10, 2025  
**Store context:** Basecamp and Backwoods · Week 1 plan is **traffic/sales to Shopify PDP**, not lead forms — see `marketing-plan.md`, `notes/meta-ad-standards.md`.

This is a **working summary for agents**, not legal advice. Full terms control; escalate legal/privacy questions to **human**.

Also apply (these Lead terms do not replace ad purchase rules):

| Doc | URL / path |
|-----|------------|
| Meta Terms of Service | https://www.facebook.com/legal/terms · `notes/meta-terms-of-service.md` |
| Commercial Terms | https://www.facebook.com/legal/commercial_terms |
| Self-Serve Ads Terms | https://www.facebook.com/legal/self_service_ads_terms |
| Advertising Standards | https://transparency.meta.com/policies/ad-standards/ · `notes/meta-ad-standards.md` |
| Platform Terms | https://developers.facebook.com/terms/ |
| Pages, Groups and Events | https://www.facebook.com/policies_center/pages_groups_events |
| Instagram Terms (if IG) | https://help.instagram.com/581066165581870 |

On conflict with Meta ToS / Instagram ToU: **these Lead Ad Terms govern** only for Lead Generation Features, and only to the extent of the conflict.

---

## What “Lead Generation Features” are

Meta features that let a user send **email or other user information** to the advertiser, including:

- **Lead Ad** (paid lead-gen ad unit)  
- **Organic** lead generation unit  
- **Lead generation messaging** experiences  

Collectively: **Lead Generation Features**.  
**Lead Generation Data** = info the user elects to send (e.g. name, email, and any additional fields).

If you accept these terms **on behalf of a third party**, you must have authority to bind them.

---

## Basecamp / ShopifyDS default stance

| Default | Reason |
|---------|--------|
| **Prefer Website / Sales / Traffic** ads to Shopify PDP | Week 1 hero path; fewer PII obligations |
| **Do not create Lead Ads** unless human explicitly requests | Triggers these terms + privacy/consent duties |
| If Lead Ads are used later | Follow this note + Ad Standards sensitive-field bans |

Ad Standards already ban many sensitive lead-form questions without permission (`notes/meta-ad-standards.md` § lead ads).

---

## Section-by-section agent rules

### A. Lead Generation Data and restrictions

- **Lead Generation Data** = what the user chooses to send via the feature.  
- **Do not target minors.**  
- **Do not collect** data that is sensitive or prohibited by **Advertising Standards**.  

**Agent:** No under-18 targeting for lead gen. No banned/sensitive fields (SSN, health, passwords, etc. per Ad Standards).

### B. Disclosures to Meta users

- Each Lead Generation Feature must include **all disclosures and choice mechanisms** required by law.  
- Include any necessary **Offer Terms** promoted in the unit (qualify criteria, expiration, redemption limits, etc.).

**Agent:** Do not launch lead forms without clear offer terms + privacy disclosure links as the human/legal requires.

### C. Compliance requirements

- Use Lead Generation Data only under **applicable laws** (privacy, advertising, telemarketing, etc.).  
- Advertiser is responsible for **permissions, disclosures, and choices** regardless of how data is obtained.  
- On the **Facebook Page/profile or Instagram account**, provide a way for users to **contact you**, and **respond** to requests about how Lead Generation Data is used.

**Agent:** Page must have contact path; do not ignore data-use inquiries. Telemarketing/SMS from leads needs human-approved compliance.

### D. Limitations on use of Lead Generation Data

- Use data **only as these terms allow**.  
- If using data for any purpose **other than** the service associated with the **call-to-action** in the feature → obtain **necessary consent**.  
- Honor Offer Terms and any consents / extra terms (including linked privacy policy) the user agreed to.

**Agent:** CTA says “get discount / contact for quote” → do not resell list, do not cold-email unrelated products without proper consent. Match use to stated purpose.

### E. Do not sell; affiliate and agency use

- **May not sell** Lead Generation Data **under any circumstances**.  
- Transfer only if recipient uses data **only to fulfill the collection purpose** (described by reasonably prominent notice and agreed at collection).  
- Sharing with third parties is **at your own risk**; ensure they comply with these terms + law.  
- If receiving data **on behalf of an advertiser**: use/share **only for that advertiser**; **do not** augment, **commingle**, or **supplement** with data from any other advertiser.

**Agent:** Never sell lead lists. Never merge Basecamp leads with other advertisers’ data. CRM/email tools only as processors for this store’s stated purpose.

### F. Security

- Maintain appropriate **technical and organizational** security measures against unauthorized/unlawful processing and accidental loss/destruction/damage.  
- Data may be delivered via Meta protocols/APIs → use must comply with **Platform Terms**.

**Agent:** No leads in git, STATUS, public chats, or unencrypted dumps. Store only in approved business tools; tokens under `~\.meta-link\` only.

### G. Modification and termination

- Meta may modify, suspend, terminate, or discontinue Lead Generation Features anytime.  
- Advertiser may stop using them anytime.

**Agent:** Do not depend on Lead Ads as the only acquisition channel; Shopify + pixel path remains primary.

---

## Stacking with other rules

| Topic | Rule |
|-------|------|
| Ad inventory purchase | Still under Advertising Standards + Self-Serve Ads Terms, etc. |
| Monitoring | Meta may **monitor or audit** compliance |
| Updates | Meta may update these terms; continued use = acceptance |
| Week 1 budget | Still ≤ **$25/wk** — lead gen does not raise the cap |

---

## ShopifyDS agent checklist

1. Official terms: https://www.facebook.com/legal/leadgen/tos  
2. **Default: no Lead Ads** for Basecamp Week 1 — use website conversion/traffic to PDP.  
3. If human orders Lead Ads: no minors; no sensitive/prohibited fields; full legal disclosures + Offer Terms.  
4. Use leads **only** for the CTA purpose; extra uses need consent.  
5. **Never sell** leads; no commingling with other advertisers.  
6. Secure storage; never commit PII to the repo.  
7. Page/IG contact path + answer data-use questions.  
8. API download of leads → Platform Terms; keep scopes minimal.  
9. On uncertainty → **human**; do not invent privacy policy text.  
10. Cross-check Ad Standards lead-form bans: `notes/meta-ad-standards.md`.

---

## Related team docs

| Doc | Role |
|-----|------|
| `notes/meta-ad-standards.md` | Ad content + sensitive lead fields |
| `notes/meta-terms-of-service.md` | Base ToS |
| `notes/meta-marketing-api-setup-2026-07-28.md` | Tokens / ad account |
| `notes/meta-budgets-spending-limits.md` | Spend vocabulary |
| `marketing-plan.md` | Week 1 Meta recipe (PDP-first) |
