# Active Legal Cases & Matters

## CASE 1: PCT Litigation Trust v. Coinbits, Inc.
**Case:** Adv. Proc. No. 25-51947 (Bankr. D. Del.)
**Arising from:** In re Prime Core Technologies Inc. bankruptcy (Case No. 23-11161, Judge Stickles)
**PCT represented by:** McDermott Will & Schulte
**Coinbits counsel:** Robert J. Gayda and Laura Miller at Seward & Kissel LLP
**Claim:** 9.094 BTC transferred during the May 16 – August 14, 2023 preference period

### Strategy
Motion to dismiss or early summary judgment, then settlement from strength.

### Key Defense Facts (CRITICAL — memorize these)
1. `admin@coinbitsapp.com` was an **automated server identity** tied to Coinbits' integrator API key at Prime Trust — not Maher personally initiating transfers
2. PT's KYC requirements necessitated a human identity be registered to the API credentials
3. ToU language stating Coinbits "will own in full" the cryptocurrency was a **legacy artifact from the Evolve Bank era** (pre-2020) — BTC withdrawals weren't permitted then; when Coinbits transitioned to Prime Trust, individual user custody accounts were established but the ToU was never updated
4. During the Prime Trust era: BTC sat in **individual user custody accounts at PT** — not in any Coinbits-owned omnibus account
5. Every Coinbits user executed the **Prime Trust User Agreement directly with PT** via iframe during onboarding
6. Nothing from preference-period withdrawals ever landed in a Coinbits-controlled wallet
7. All transfers went from PT's hot wallet directly to **user external addresses**
8. All preference-period withdrawals were **user-initiated** through the Coinbits UI and fully automated
9. Coinbits **deposited 1 BTC into Prime Trust** during the preference period — directly undermining any inference of insider knowledge of PT's insolvency
10. **Discovery custodians:** Yousef Janajri and Dave Birnbaum (VP Product)
11. Dave Birnbaum's technical confirmation: PT API keys were issued to integrators indexed to an integrator email address; user withdrawal requests automatically triggered Coinbits' system to hit the PT API using that key with a user-specific payload; PT independently evaluated each request without Coinbits visibility

### Legal Arguments for Dismissal
- Coinbits was a **mere conduit/pass-through** — never had beneficial ownership of the BTC
- The transfers were from PT to users, not from PT to Coinbits
- No "transfer of an interest of the debtor in property" as required under §547(b)
- Coinbits received no benefit from these transfers
- The 1 BTC deposit during the preference period negates any inference of knowledge of insolvency

### Pending Actions
- Track deadlines from Seward & Kissel — flag 72 hours in advance
- Monitor for settlement signals from PCT

## DEAL STRUCTURES REQUIRING LEGAL REVIEW

### Red House Roasters Acquisition
- Stock purchase, $2M cash + $700K earnout
- Earnout tied to wholesale revenue retention + top account retention
- No signed customer contracts across wholesale base (key risk)
- 60-day exclusivity, 45-day diligence, 10% escrow holdback
- 180-day paid transition for Richard
- Need to review: assignment of leases, IP transfer, employee transition, non-compete

### Somerville Plaza
- Two adjacent properties, same seller (Qiku, Selim & Begishe)
- B-4 zoning — confirm food, fitness, assembly permitted
- Lot consolidation or shared parking may need variance
- Phase acquisition approach

### Halal Revenue-Based Financing
- Must get scholar sign-off before any deployment
- Structure: capital deployed → repaid via daily % of gross revenue
- Cap multiples: 1.3–1.65x
- First pilot: $5M to ecommerce fashion business
- Key risks: fashion inventory recovery (10-20 cents on liquidation), concentration risk, existing liens
