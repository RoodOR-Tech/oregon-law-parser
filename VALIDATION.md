# Unseen Validation Protocol

The release-certifying 50-law corpus in `gold/manifest.json` is frozen and remains the regression/certification benchmark. Validation work must not modify that benchmark merely to improve validation metrics.

## Unseen validation set

The first unseen validation set contains 25 Oregon session laws selected on branch `validation/unseen-25` from certified master commit `b181cb61949b864163e3a4401e509f5a3e92cdd3`.

Selection was frozen before parser evaluation. The initial candidate file intentionally contains source URLs and sampling tags but no expected metadata or ORS change labels. This prevents parser output from influencing independent review.

The selection spans 2005, 2007, 2011, 2021 and 2023 and deliberately includes legacy HTML and PDF sources, single amendments, large multi-section acts, mixed amendment/repeal cases, emergency clauses, delayed/prescribed effective dates, added-to provisions, prior-session-law references, same-session-law changes and conditional amendments.

## Review sequence

1. Freeze the candidate roster before parser execution.
2. Hash every authoritative Oregon Legislature source and pin source format, byte count and SHA-256.
3. Independently review each source and record expected year, chapter, bill, effective date, amended ORS sections and repealed ORS sections using the authoritative chapter text and applicable comparative section tables.
4. Record review basis and review sources. Do not use parser output to establish expectations.
5. Only after all 25 expectations are frozen, acquire the pinned fixtures and run the parser against the validation set.
6. Publish validation precision, recall, metadata exact match, per-document failures and conflict diagnostics separately from the frozen 50-law certification metrics.
7. If validation exposes parser defects, fix parser behavior on a new branch and rerun both the frozen 50-law certification corpus and the untouched validation expectations. Do not rewrite independently reviewed validation labels merely to make the parser pass.

## Interpretation

The unseen validation set is not part of release certification and does not increase the 50-law gold count. Its purpose is to estimate generalization outside the corpus used during hardening.

A clean result is stronger evidence than continued tuning on the frozen benchmark. A failure is useful evidence and should remain visible until the underlying parser defect is understood.
