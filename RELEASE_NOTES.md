# Release Notes

## v1.0.0-rc1 readiness baseline

The parser has reached a release-certifying 50-law benchmark built from independently reviewed Oregon session laws and authoritative legislative sources.

### Certification

- Gold documents: 50
- Section precision: 1.000
- Section recall: 0.9981
- Metadata exact match: 1.000
- Release certification: true
- Certifying CI: #100
- Certifying candidate head: `01f7fb379597c7ba00dacfb4f14d5819b120b6a5`
- Certified corpus merge: `af283ac5919e84d50e01070db18fa5c5c9b66072`

### Reliability characteristics covered

The frozen certification corpus includes positive and negative controls, single and multiple amendments, mixed amendment/repeal laws, multiple ORS repeals, incidental ORS citations, added-to provisions, prior- and same-session-law changes, emergency clauses, delayed effective dates, special sessions, degraded-layout PDFs, legacy HTML, and large multi-section acts.

### Release gate

CI now requires the gold-quality report to satisfy all of the following on every pull request and master push:

- `gatePassed == true`
- `releaseCertifying == true`
- `goldDocuments >= releaseCertificationMinimumDocuments`

The benchmark governance rules are documented in `CERTIFICATION.md`.

### Known limitation

The frozen corpus contains one known false negative: the amendment of ORS 697.612 in Oregon Laws 2009 chapter 604 (HB 2191). The gold expectation remains authoritative and unchanged. See `KNOWN_ISSUES.md`.

### Next validation phase

Further reliability work should use a separate unseen validation corpus rather than repeatedly tuning against the frozen 50-law certification set. A first external-validation tranche should target 25 independently selected laws and preserve the same authoritative-source, hash, provenance, and conflict-diagnostic discipline.
