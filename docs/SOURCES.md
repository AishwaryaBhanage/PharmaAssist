# Sources

Documents in the corpus, all downloaded on 2026-10-13. Structured metadata for each is in [`catalog.yaml`](catalog.yaml).

## Diabetes

| File | Title | Publisher | Program | Type | Authority | Date | Pages |
|---|---|---|---|---|---|---|---|
| [va_dod_cpg_diabetes_2023.pdf](https://www.healthquality.va.gov/guidelines/CD/diabetes/VADoD-Diabetes-CPG_Final_508.pdf) | VA/DoD Clinical Practice Guideline for the Management of Type 2 Diabetes Mellitus (v6.0) | VA / DoD | VA | Clinical guideline | Advisory | 2023-05 | 165 |
| [va_pbm_t2dm_clinicians_guide.pdf](https://www.pbm.va.gov/PBM/AcademicDetailingService/Documents/508/IB10-1402_Type2DiabetesCliniciansGuide_508Conformant.pdf) | A VA Clinician's Guide to Diabetes Management in Primary Care (IB 10-1402) | VA PBM Academic Detailing | VA | Clinician guide | Advisory | 2020-05 | 24 |
| [va_pbm_t2dm_pharmacotherapy_2025.pdf](https://www.pbm.va.gov/PBM/AcademicDetailingService/Documents/508/IB10-1775_PharmacotherapyforT2DM_P97221.pdf) | Pharmacotherapy for T2DM 2025: A VA Clinician's Summary (IB 10-1775) | VA PBM Academic Detailing | VA | Clinician guide | Advisory | 2025-04 | 16 |

## Opioids

| File | Title | Publisher | Program | Type | Authority | Date | Pages |
|---|---|---|---|---|---|---|---|
| [va_dod_cpg_opioids_2022.pdf](https://www.healthquality.va.gov/guidelines/Pain/cot/VADoDOpioidsCPG.pdf) | VA/DoD Clinical Practice Guideline for the Use of Opioids in the Management of Chronic Pain (v4.0) | VA / DoD | VA | Clinical guideline | Advisory | 2022-05 | 177 |
| [va_pbm_bup_chronic_pain.pdf](https://www.pbm.va.gov/PBM/AcademicDetailingService/Documents/Academic_Detailing_Educational_Material_Catalog/IB_1497_Provider_BupChronicPain.pdf) | Buprenorphine for Chronic Pain (IB 10-1497) | VA PBM Academic Detailing | VA | Clinician guide | Advisory | 2021-05 | 4 |
| [va_pbm_bup_oud.pdf](https://www.pbm.va.gov/PBM/AcademicDetailingService/Documents/508/10-1498_OUD_Provider_BuprenorphineforOUD_P97021.pdf) | Buprenorphine for Opioid Use Disorder: Clinician Guide (IB 10-1498) | VA PBM Academic Detailing | VA | Clinician guide | Advisory | 2023-03 | 4 |
| [cms_partd_dmp_guidance_2019.pdf](https://www.cms.gov/medicare/prescription-drug-coverage/prescriptiondrugcovcontra/downloads/2019-part-d-drug-management-program-policy-guidance-memo-november-20-2018-.pdf) | Part D Drug Management Program Policy Guidance (CY 2019) | CMS | Medicare Part D | Policy memo | Binding | 2018-11-20 | 41 |
| [cms_partd_opioid_pharmacists_2022.pdf](https://www.cms.gov/files/document/medicare-part-d-opioid-policies-information-pharmacists-december-19-2022.pdf) | Medicare Part D Opioid Policies: Information for Pharmacists | CMS | Medicare Part D | Pharmacist guidance | Summary of binding policy | 2022-12-19 | 2 |

## Cross-theme (diabetes and opioids)

| File | Title | Publisher | Program | Type | Authority | Date | Pages |
|---|---|---|---|---|---|---|---|
| [va_national_formulary_2026_09.xlsx](https://www.pbm.va.gov/PBM/nationalformulary/VA_National_Formulary_SEPT_2026.xlsx) | VHA National Formulary | VA PBM Services | VA | Formulary | Binding | 2026-09 | – |
| [ny_medicaid_pdl.pdf](https://newyork.fhsc.com/downloads/providers/NYRx_PDP_PDL.pdf) | NYRx Preferred Drug List | NYS Dept. of Health (NYRx) | NY Medicaid | Preferred drug list | Binding | 2026-09-14 | 86 |
| [ny_medicaid_pharmacy_policy.pdf](https://www.emedny.org/ProviderManuals/Pharmacy/PDFS/Pharmacy_Policy_Guidelines.pdf) | NYRx Pharmacy Manual Policy Guidelines (2026-3) | NYS Dept. of Health (NYRx) | NY Medicaid | Pharmacy manual | Binding | 2026-09 | 50 |

Dates are the publication or revision date printed in each document. The CMS pharmacist guidance doesn't print a date; its date comes from the title it is published under, the source URL and the PDF metadata.

## Notes

- The February 2026 VA formulary link returned 404 on 2026-10-13; the September 2026 version from the VA National Formulary page was used instead.
- Four documents (2 VA/DoD guidelines, 2 CMS) had to be downloaded manually because those sites block automated downloads.

## Preprocessing in one paragraph, and what is skipped

PDFs are parsed with Docling (layout, text, tables with their structure, OCR for bitmap pages), figures are
inventoried from the PDF itself and interpreted once by a vision model with deterministic checks
(`reports/parsing/VISUAL_EXTRACTION.md`); text is cut into parent sections and 350-token child chunks with the
heading path kept (`src/pharmassist/chunkers/`); the VA formulary spreadsheet and the NY PDL drug pages become
table rows served by two lookup tools instead of chunks (`scripts/build_tables.py`, `src/pharmassist/tables/`).
Skipped on purpose: running headers and footers (lines repeated on more than half the pages,
`src/pharmassist/chunkers/sections.py` `_repeated_lines`), tables of contents, 157 of 207 embedded images
judged decorative (logos, icons, tiny images; `reports/parsing/VISUAL_EXTRACTION.md`), the NY PDL's drug-class
pages as prose (they are read as rows instead), and spreadsheet rows without a drug name. Nothing else in the 11
documents is dropped; every chunk keeps its page numbers, so citations resolve to the printed page.
