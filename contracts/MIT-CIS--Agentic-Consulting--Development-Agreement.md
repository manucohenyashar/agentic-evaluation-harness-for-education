# SOFTWARE DEVELOPMENT AND LICENSE AGREEMENT

**Between**

**Agentic Consulting**, a sole proprietorship of **Emmanuel Cohen-Yashar** ("**Consultant**"),
having its principal place of business at [ADDRESS]

**and**

**Massachusetts Institute of Technology**, a Massachusetts non-profit corporation, acting through
its **Center for International Studies** ("**MIT**"), having a place of business at
1 Amherst Street, Cambridge, MA 02142

**Effective Date:** [DATE]
**Program:** "Empowering the Teacher," MIT Center for International Studies
**Agreement No.:** [MIT PO / AGREEMENT NUMBER]

---

> **Drafting note — delete before execution.** This is a negotiation draft prepared for the
> Consultant. It is not legal advice. Both parties should have it reviewed by counsel, and MIT will
> route it through its Office of the Vice President for Finance / Procurement and, where research
> collaboration is contemplated, the Technology Licensing Office (TLO). **Article 8 (Intellectual
> Property) deliberately departs from a work-made-for-hire structure** and is the clause most likely
> to be negotiated; see Section 8.2 and the recitals for the basis on which that position rests.

---

## RECITALS

**A.** Consultant is the sole author of a technical design specification titled *"Agentic Evaluation
for Education: A Research-Grounded Architecture for a Local, Open-Source Grading Harness"*
(the "**Design Document**"), which Consultant conceived, authored, and reduced to writing **prior to
the Effective Date and independently of MIT**, using no MIT funds, facilities, personnel, or
confidential information. The Design Document, together with the architecture, methods, schemas, and
know-how it embodies, constitutes Consultant Background IP under Section 8.1.

**B.** MIT operates the "Empowering the Teacher" program at its Center for International Studies,
which seeks to make substantive assessment feasible for teachers in large classes (150–350 students),
including in settings with limited or intermittent network connectivity.

**C.** MIT wishes to engage Consultant to implement, deploy, and validate a working system based on
the Design Document (the "**Platform**"), and to license the Platform for MIT's research and
educational use.

**D.** The parties intend that Consultant deliver the Platform as a **licensed product developed
under a services engagement**, and expressly **not** as a work made for hire, on the basis that the
Platform is a derivative and extension of Consultant Background IP that materially pre-dates this
Agreement.

NOW, THEREFORE, in consideration of the mutual covenants below, the parties agree as follows.

---

## ARTICLE 1 — DEFINITIONS

**1.1 "Acceptance Criteria"** means the objective, testable criteria stated for each Gate in
Schedule A.

**1.2 "Background IP"** means all Intellectual Property owned or controlled by a party as of the
Effective Date, or developed thereafter outside the scope of this Agreement, including for Consultant
the Design Document and all prior tooling, libraries, harnesses, and know-how.

**1.3 "Collaborative Invention"** means an invention or work of authorship conceived or first reduced
to practice jointly by Consultant Personnel and MIT Personnel in the course of a collaboration
governed by an executed Joint Development Addendum under Section 8.5.

**1.4 "Deliverable"** means any software, source code, documentation, report, test result, or other
work product identified in Schedule A.

**1.5 "Foreground IP"** means Intellectual Property first created in the course of performing the
Services, excluding Collaborative Invention IP.

**1.6 "Gate"** means a milestone identified in Schedule A, the acceptance of which triggers a payment
under Schedule B.

**1.7 "Intellectual Property"** or **"IP"** means patents and patent applications, copyrights,
trade secrets, know-how, database rights, and all other proprietary rights, excluding trademarks.

**1.8 "MIT Data"** means all data supplied by or on behalf of MIT or a Participating School,
including assessments, rubrics, answer keys, model answers, curricula, student submissions, teacher
scores, and any derived records identifying a student or teacher.

**1.9 "Participating School"** means an educational institution participating in the Program under
MIT's direction.

**1.10 "Pass-Through Costs"** means the hosted inference (token) charges described in Article 7 and
Schedule D, borne by MIT. Pass-Through Costs do not include equipment; MIT-Furnished Equipment is
governed by Section 7.6 and is not a cost item under this Agreement.

**1.11 "Personal Data"** means information relating to an identified or identifiable individual,
including "education records" as defined by FERPA (20 U.S.C. § 1232g).

**1.12 "Platform"** means the software system implementing the Design Document, in source and object
form, including all components, schemas, prompts, configurations, test harnesses, and documentation
delivered under this Agreement.

**1.13 "Services"** means the development, deployment, validation, training, and support work
described in Article 2 and Schedule A.

---

## ARTICLE 2 — SCOPE OF SERVICES

**2.1 Overview.** Consultant shall design, build, deploy, and validate the Platform in two
successive deployment profiles:

- **(a) Cloud-hosted profile** (`cloud-hosted` / `dev-ci` per the Design Document §0.7, §8.7). All
  development, continuous integration, and the first end-to-end feasibility pilot run against
  open-weight models served through a hosted inference provider.
- **(b) Edge-local profile** (`edge-local` per §8.1). The identical codebase, selected by
  configuration through a single provider abstraction, deployed to Apple Silicon hardware and
  validated by the hardware acceptance test of §8.5.

**2.2 No backend-specific code paths.** Consultant shall implement all model access through one
provider abstraction (Design Document R27). No stage of the pipeline shall contain a
backend-specific code path. Satisfaction of this requirement is an Acceptance Criterion at Gate G1
and is re-tested at every subsequent Gate.

**2.3 Build order.** Consultant shall follow the implementation sequence of Design Document §12,
under which version pinning, judgment isolation, the provider abstraction with backend-scoped
validation records, the ingestion validation ladder, and the persistence work-ledger are built in
the first phase rather than retrofitted.

**2.4 Scope boundary.** The Services do **not** include: creation of curricula or assessment
content; scanning or digitization of student work; procurement or operation of MIT's network,
identity, or student information systems; teacher recruitment; IRB/COUHES submissions; or
translation and localization beyond the language(s) named in Schedule A.

**2.5 Personnel.** Emmanuel Cohen-Yashar shall act as technical lead and shall personally perform or
directly supervise all Services. Consultant may engage subcontractors provided Consultant remains
fully responsible for their performance and binds them to confidentiality, data-protection, and IP
assignment terms no less protective than this Agreement.

**2.6 Development method is Consultant's to choose.** MIT engages Consultant for the delivered
result, not for a quantity of labour. Consultant may use AI-assisted software development tools and
its own pre-existing generation and orchestration harnesses (which are Consultant Background IP under
Section 8.1) to produce the Platform. Consultant remains fully responsible for the correctness,
licensing, and security of everything it delivers, and every Deliverable is subject without
modification to the Acceptance Criteria in Schedule A. **The fees in Schedule B are a package price
for the delivered and accepted result and are not adjustable by reference to hours worked or to the
method of production.**

**2.7 Site access.** Where a Gate requires testing at a Participating School, MIT shall arrange
access, consents, and logistics. Delay attributable to MIT site access extends the affected schedule
day-for-day.

**2.8 Test corpora: real data for quality, scaled corpora for throughput.** The parties record that
the teacher-supplied dataset available at the Effective Date is small, and that this is not an
obstacle, because the two properties being tested need different corpora:

- **(a) Grading quality, transcription fidelity, and agreement statistics** are tested against
  **real** teacher-supplied submissions in the actual medium. These runs are small by nature and are
  the substance of Gates G2, G4, and G5.
- **(b) Throughput, memory ceiling, resumability, thermal sustain, and disk growth** are tested
  against a **scaled corpus** of approximately 350 submissions, assembled by Consultant from the real
  submissions by augmentation — rescanning, re-imaging, permutation, and synthesis in the same
  medium. Design Document §12 expressly contemplates this, noting that a throughput failure is
  "far cheaper to discover on 350 synthetic submissions than at a pilot site."

**A scaled corpus is valid evidence for the Gate G6 metrics in criteria A39–A42 and is not valid
evidence for any agreement, κ, or grading-quality figure.** Consultant shall state which corpus
produced each reported figure in every Gate Report, consistent with Section 4.6.

---

## ARTICLE 3 — DELIVERABLES AND GATES

**3.1** Deliverables, Gates, and Acceptance Criteria are set out in **Schedule A**. Each Gate is a
discrete, independently valuable increment.

**3.2 Gate dates are targets; time is not of the essence.** Consultant performs the Services as an
independent contractor and **controls the manner, method, sequence, and timing of its work**
(Section 17.1). Consultant does not undertake to devote any particular number of hours, to work on
any particular days, or to be available during any particular hours. The Gate target dates in
Schedule A and Schedule B are **planning estimates, not binding deadlines**, and **time is not of the
essence** as to any of them. MIT's remedies for delay are those in Section 3.4, and no other.

**3.3 Coordination windows.** Activities requiring MIT personnel, teachers, or Participating School
staff — Gate G4 setup and elicitation, the Gate G5 pilot, and Gate G7 training and the unassisted run
— shall be scheduled by agreement with **not less than ten (10) business days' notice**, in blocks,
at times workable for both parties. Neither party is obliged to be available outside times so agreed.

**3.4 Long-stop date.** If Gate G7 has not been accepted within **twelve (12) months** of the
Effective Date, extended by any period of MIT-caused delay under Sections 2.7, 3.3, 7.6(d), 17.2, or
Article 18, either party may terminate on thirty (30) days' written notice. On such termination MIT
pays for all accepted Gates and for work in progress on the current Gate on the pro-rata basis in
Section 14.2(b), and retains the license in Section 8.3 as to accepted Deliverables. **Failure to meet
a Gate target date is not, of itself, a material breach**; the long-stop date in this Section is the
parties' sole schedule remedy.

**3.5 Feasibility gates are real gates.** Gate **G5** (cloud feasibility pilot) and Gate **G6**
(hardware acceptance test) are pass/fail engineering gates as contemplated by Design Document §8.5
and §12 ("Phase 1.5, prove it on hardware"). A failed measurement at G5 or G6 is a finding of the
engagement, not a breach, and is handled under Section 13.3 and Section 13.4.

---

## ARTICLE 4 — ACCEPTANCE PROCEDURE

**4.1 Submission.** Consultant shall notify MIT in writing when a Gate is ready for review and shall
deliver the associated Deliverables together with a **Gate Report** stating, criterion by criterion,
the measured result against each Acceptance Criterion.

**4.2 Review period.** MIT shall have **ten (10) business days** from delivery to accept or to give
written notice of non-conformity identifying, with specificity, each Acceptance Criterion not met.

**4.3 Deemed acceptance.** If MIT gives no written notice within the review period, or places the
Deliverable into productive use with real student submissions, the Gate is deemed accepted.

**4.4 Cure.** On a valid notice of non-conformity, Consultant shall have **twenty (20) business
days** to cure and resubmit. Two failed cure cycles on the same criterion entitle MIT to the remedies
in Section 13.3.

**4.5 No unstated criteria.** MIT may not withhold acceptance on grounds other than a failure to meet
a stated Acceptance Criterion in Schedule A. New requirements proceed through Article 12 (Change
Control).

**4.6 Measurement honesty.** Consistent with Design Document R8, Gate Reports shall state
chance-corrected agreement figures with the sample size attached, shall report judged and
deterministic (multiple-choice) items separately (R53), and shall not present raw percent-agreement
as an accuracy claim. A Gate Report that overstates a measured result is a material breach.

---

## ARTICLE 5 — FEES

**5.1 Fixed fee.** In consideration of the Services, MIT shall pay Consultant a fixed fee of
**US $135,000** (the "**Fixed Fee**"), payable in tranches on acceptance of each Gate as set out in
**Schedule B**.

**5.2 Progressive compensation and final retention.** The parties acknowledge that the Services
represent a substantial development effort undertaken before any working system exists. Accordingly
the Fixed Fee is earned progressively against accepted Gates, and **ten percent (10%) of the Fixed
Fee is withheld until Final Acceptance at Gate G7**, which requires a demonstrably working end-to-end
system.

**5.3 Invoicing and payment.** Consultant shall invoice on acceptance of each Gate. MIT shall pay
undisputed invoices within **thirty (30) days** of receipt. Amounts properly disputed in writing
within fifteen (15) days may be withheld pending resolution; all other amounts shall be paid.

**5.4 Late payment.** Undisputed amounts unpaid after forty-five (45) days accrue interest at the
lesser of 1.0% per month or the maximum rate permitted by Massachusetts law.

**5.5 Taxes.** Fees are exclusive of sales, use, and similar taxes. Each party bears its own income
taxes. MIT shall provide its tax-exemption certificate where applicable.

**5.6 Optional support.** Post-acceptance support, if elected by MIT, is priced in Schedule B
Section B.4 and is not included in the Fixed Fee.

---

## ARTICLE 6 — EXPENSES AND TRAVEL

**6.1 No travel expense is budgeted.** Consultant is located in Andover, Massachusetts, within
routine commuting distance of MIT's Cambridge campus. Attendance at MIT and at any Participating
School in the greater Boston area is included in the Fixed Fee and is **not** separately chargeable
or reimbursable. No travel allowance appears in Schedule D.

**6.2 Out-of-area travel only.** If MIT requires Consultant to attend a site outside New England,
such travel shall be pre-approved in writing and reimbursed at cost against receipts in accordance
with MIT travel policy, with travel time chargeable at fifty percent (50%) of the daily rate in
Schedule B Section B.4 where travel exceeds one working day each way. The parties do not presently
anticipate any such travel.

---

## ARTICLE 7 — INFERENCE COSTS AND MIT-FURNISHED EQUIPMENT

**7.1 The only Pass-Through Cost is inference tokens.** MIT shall bear one hundred percent (100%) of
hosted inference (token) charges through OpenRouter or an equivalent provider, for development,
testing, stress testing, and the Gate G5 feasibility pilot. The indicative budget is **Schedule D**.

The parties record their shared expectation that this cost is **small in absolute terms**, for two
reasons stated here so that Schedule D is understood rather than merely agreed:

- **(a)** Ordinary development and functional testing run against a handful of submissions at a
  time, not a full cohort. Full-cohort runs occur only at the stress-testing and acceptance points
  (Gates G3, G5, and G6).
- **(b)** A full 350-submission run consumes on the order of tens of dollars of open-weight
  inference, and the recorded-fixture provider required by Design Document §12 lets the majority of
  the test suite re-run at zero token cost.

Consultant does not require, and MIT is not asked to fund, dedicated cloud compute, managed CI
infrastructure, or third-party developer subscriptions. Consultant performs all development on its
own equipment at its own cost.

**7.2 Preferred mechanism: an MIT-held inference account.** MIT shall establish and hold the
inference-provider account in MIT's own name and grant Consultant access with a spend limit. This
places token spend directly on MIT and avoids markup and reimbursement lag. MIT may alternatively
issue Consultant a prepaid credit on that account.

**7.3 Reimbursement where MIT accounts are not available.** Where Consultant incurs a Pass-Through
Cost on MIT's behalf with MIT's prior written approval, MIT shall reimburse **at cost, without
markup**, against invoices and supporting statements, within thirty (30) days.

**7.4 [Reserved.]** Equipment is addressed at Section 7.6.

**7.5 Spend control.** Consultant shall configure and enforce a per-run cost ceiling (Design Document
R5) and shall report token spend monthly. Consultant shall notify MIT before exceeding **eighty
percent (80%)** of the Schedule D token budget. Consultant is not required to continue performance
that would exceed the approved Pass-Through budget, and any resulting delay extends the schedule
day-for-day.

**7.6 MIT-Furnished Equipment.**

**(a)** MIT shall furnish one or more Apple Silicon Mac laptops ("**MIT-Furnished Equipment**") as
the target hardware for the `edge-local` profile and Gate G6. **The provenance, procurement, and cost
of that equipment are entirely MIT's affair and are not a cost item, budget line, or reimbursable
expense under this Agreement.** Consultant makes no recommendation as to source and takes no position
on price. Schedule D contains no equipment line.

**(b)** MIT retains title. Consultant shall hold MIT-Furnished Equipment as bailee, use it solely for
the Services, and return it to MIT, or to a Participating School as MIT directs, at Gate G7 or on
earlier termination, ordinary wear excepted.

**(c)** **Specification.** For Gate G6 to be meaningful the equipment must be able to hold the judge
panel in memory. **64 GB unified memory is the reference target** (`unified-large`, Design Document
§8.1). A 32 GB machine is workable but restricts the deployment to the `unified-small` profile and
shall be agreed in writing before Gate G6 begins, since it changes what criterion A39 can be tested
against.

**(d)** **Availability is a MIT dependency.** MIT shall deliver the equipment to Consultant no later
than the date in Schedule A (dependency D5). Delay extends the G6 schedule day-for-day and does not
affect payment of earlier Gates. Gates G0 through G5 require no MIT-Furnished Equipment, as all work
to that point runs on the `cloud-hosted` profile.

**7.7 Laptop thermal constraint acknowledged.** The parties acknowledge that a laptop chassis
sustains a lower continuous inference load than a desktop chassis, and that "thermal sustain over the
full run" is an express metric of the Design Document §8.5 acceptance test. Where measurement at
Gate G6 shows that sustained thermal throttling prevents the batch window in criterion A39 from being
met on the MIT-Furnished Equipment, that is a hardware finding governed by Section 13.4, and the
parties shall address it by Change Order — by adjusting the batch window, the panel configuration, or
the equipment — rather than treating it as a failure of the Services.

---

## ARTICLE 8 — INTELLECTUAL PROPERTY

> **This Article is the commercial heart of the Agreement.**

**8.1 Background IP.** Each party retains all right, title, and interest in its Background IP.
Nothing in this Agreement transfers Background IP. For the avoidance of doubt, **the Design Document
is Consultant Background IP**, authored before the Effective Date without MIT funds, facilities,
personnel, or confidential information, as recited in Recital A.

**8.2 Ownership of the Platform — not a work made for hire.**

**(a)** Consultant is and shall remain the sole and exclusive owner of all right, title, and interest
in and to the **Platform and all Foreground IP**, including all source code, architecture, data
schemas, prompt templates, band descriptor structures, orchestration logic, evaluation harnesses, and
documentation created in performing the Services.

**(b)** The parties expressly agree that the Platform is **not a "work made for hire"** within the
meaning of 17 U.S.C. § 101, and that no provision of any MIT purchase order, procurement terms,
invoice, or click-through document shall be construed to assign, transfer, or grant MIT ownership of
the Platform or Foreground IP. In the event of conflict between this Agreement and any such document,
**this Agreement controls** (see Section 20.9).

**(c)** The basis for paragraph (a) is that the Platform is an implementation and derivative of
Consultant Background IP that materially pre-dates this Agreement, and that MIT's consideration
purchases the license in Section 8.3 and the Services, not title.

**8.3 License to MIT.** Consultant hereby grants MIT a **perpetual, irrevocable, worldwide,
non-exclusive, royalty-free, fully paid-up license**, effective as to each Deliverable upon its
acceptance, to:

**(a)** use, execute, reproduce, and internally display the Platform for MIT's **research,
instructional, and educational purposes**, including the Program;

**(b)** modify and create derivative works of the Platform for MIT's internal purposes, and to use
those derivative works under this same license (Consultant owns the underlying Platform; MIT owns its
own modifications, subject to Consultant's underlying rights);

**(c)** **sublicense** the right in (a) to Participating Schools and to MIT's academic collaborators,
solely for non-commercial educational and research use within the Program, on terms no less
protective of Consultant than this Article;

**(d)** use the Platform to generate, publish, and disseminate research results, subject to
Article 9; and

**(e)** continue all of the foregoing after expiry or termination of this Agreement, for any reason,
as to every Deliverable accepted before termination.

**8.4 What the license does not include.** The license in Section 8.3 does not permit MIT to: sell,
resell, or offer the Platform as a commercial service to third parties; grant rights to a commercial
entity for commercial exploitation; or remove Consultant's copyright notices. Any commercial use
requires a separate written license from Consultant, which Consultant shall negotiate in good faith
and on terms recognizing MIT's contribution.

**8.5 Collaboration with an MIT research laboratory — split IP.**

**(a)** The parties anticipate that MIT may wish to involve one or more MIT research laboratories in
substantive technical collaboration (for example, on judge-panel composition, calibration
methodology, bias measurement, or transcription models).

**(b)** **No such collaboration shall commence until the parties execute a Joint Development
Addendum** substantially in the form of **Schedule C**, identifying the participating laboratory, the
principal investigator, the defined field of collaboration, the contribution of each party, and the
resulting IP allocation. Work performed before such execution is governed by Sections 8.1–8.3 and
generates no MIT ownership interest.

**(c)** Under an executed Joint Development Addendum, ownership of any **Collaborative Invention** is
determined by **inventorship under United States patent law** and by authorship under United States
copyright law, applied to the actual contributions:

  1. inventions made solely by Consultant Personnel: owned solely by Consultant;
  2. inventions made solely by MIT Personnel: owned solely by MIT, subject to MIT's IP policies and
     administered by the MIT TLO;
  3. inventions made jointly: **owned jointly**, in undivided equal shares unless the Addendum states
     a different split reflecting relative contribution, with each party free to practice and to
     license the joint IP **without accounting to or consent of the other**, subject to any
     obligations to research sponsors and to Section 8.5(d).

**(d)** For jointly owned IP the parties shall agree in the Addendum on responsibility for patent
prosecution and cost-sharing, and shall grant each other a non-exclusive license to practice the
joint IP for internal research and educational purposes at no charge.

**(e)** Nothing in this Section obliges either party to enter into any collaboration.

**8.6 MIT Data and MIT materials.** MIT (or the Participating School, or the student, as applicable)
retains all right, title, and interest in MIT Data, assessments, rubrics, answer keys, model answers,
curricula, and instructional content. Consultant acquires no rights in MIT Data other than the
limited right to process it to perform the Services.

**8.7 De-identified telemetry.** Consultant may retain and use **aggregate, de-identified** technical
telemetry — throughput, latency, memory, error and retry rates, transcription failure rates, and
model-agreement statistics — to improve the Platform, provided such data contains no Personal Data,
no student work, no teacher-identifying information, and no MIT Data in any reconstructible form, and
provided MIT is not identified without permission under Article 15.

**8.8 Feedback.** MIT grants Consultant a perpetual, royalty-free license to use suggestions and
feedback provided by MIT personnel regarding the Platform, without obligation.

**8.9 Third-party and open-source components.** Consultant shall maintain and deliver a bill of
materials listing every third-party and open-source component, its version, and its license.
Consultant shall not incorporate any component under a license that would require the Platform's
source code to be disclosed or licensed to third parties (including GPL-family copyleft licenses in
a linked configuration) without MIT's prior written consent. Model weights and their licenses shall
be listed and version-pinned per Design Document §6.7.

**8.10 Escrow of source.** Consultant shall deposit the complete Platform source code, build scripts,
and deployment documentation with MIT at each Gate acceptance, in a repository MIT controls. This
deposit is made under, and is subject to, the license in Section 8.3 and the confidentiality
obligations of Article 10, and effects no transfer of ownership.

**8.11 AI-assisted generation, and allocation as between the parties.**

**(a)** MIT acknowledges that portions of the Platform may be produced using AI-assisted development
tools under Consultant's direction, per Section 2.6.

**(b)** The parties acknowledge that the copyright status of purely machine-generated material is
unsettled in some jurisdictions. **As between MIT and Consultant, all right, title, and interest in
the Platform and Foreground IP is allocated to Consultant under Section 8.2 regardless of the manner
of production, and MIT shall not assert any ownership interest in the Platform on the ground that any
part of it was machine-generated.** MIT's rights are those expressly granted in Section 8.3.

**(c)** Consultant's proprietary position in the Platform rests, without limitation, on: the
copyright in the Design Document (Recital A); the copyright in Consultant's human-authored selection,
arrangement, direction, integration, and modification of all material comprising the Platform; trade
secret protection in the Platform's architecture, schemas, prompt formulations, and configurations;
and the contractual allocation in this Article. Consultant shall maintain the Platform's
confidentiality accordingly, and MIT shall treat the source code deposited under Section 8.10 as
Consultant Confidential Information under Article 10.

**(d)** Consultant warrants that it has reviewed all delivered code, that its use of AI-assisted
tools does not subject the Platform to any third-party license obligation, and that Section 8.9
(third-party and open-source components) and Section 13.1(c) (non-infringement) apply to
machine-assisted output exactly as to hand-written code.

**8.12 No implied licenses.** Except as expressly granted, no license is granted by implication,
estoppel, or otherwise.

---

## ARTICLE 9 — PUBLICATION

**9.1 MIT's right to publish.** MIT and its personnel shall be free to publish and present the
results of research conducted using the Platform, including validation statistics, pedagogical
findings, and evaluations of system performance. Consultant shall not have the right to veto,
suppress, or require alteration of any publication's scientific content.

**9.2 Review window.** MIT shall furnish Consultant a copy of any proposed publication at least
**thirty (30) days** before submission. Consultant may within that period request (a) removal of
Consultant Confidential Information, which MIT shall honor, and (b) a delay of up to a further
**sixty (60) days** to permit a patent filing. No other delay may be requested.

**9.3 Reciprocity.** Consultant shall likewise furnish MIT thirty (30) days' notice of any
publication describing the Program, MIT Data, or results obtained at a Participating School, and
shall remove MIT Confidential Information on request. Publication by Consultant naming MIT is
additionally subject to Article 15.

**9.4 Attribution.** Publications describing the Platform shall attribute its architecture and
implementation to Emmanuel Cohen-Yashar / Agentic Consulting, with a citation to the Design Document
as agreed by the parties.

**9.5 Student work.** No publication by either party shall include student work or teacher scores
except in de-identified or paraphrased form consistent with Article 11 and Design Document §9.4.

---

## ARTICLE 10 — CONFIDENTIALITY

**10.1** Each party ("Receiving Party") shall protect the other's information disclosed in confidence
and marked or reasonably identifiable as confidential ("Confidential Information") using at least the
care it applies to its own confidential information, and no less than reasonable care, and shall use
it solely to perform this Agreement.

**10.2 Exclusions.** Confidential Information does not include information that is or becomes public
without breach, was rightfully known without obligation, is independently developed, or is rightfully
received from a third party without restriction.

**10.3 Compelled disclosure.** A Receiving Party may disclose Confidential Information where legally
compelled, provided it gives prompt notice (where lawful) and reasonable cooperation to seek
protective treatment.

**10.4 Term.** Obligations survive for **five (5) years** after termination, except that MIT Data
containing Personal Data and Consultant's trade secrets are protected for so long as they remain
protectable.

**10.5 Academic freedom.** Nothing in this Article restricts MIT's rights under Article 9.

---

## ARTICLE 11 — DATA PROTECTION AND STUDENT PRIVACY

**11.1 Roles.** As between the parties, MIT (and each Participating School) is the controller of
MIT Data. Consultant processes MIT Data solely as a service provider on MIT's documented
instructions, and shall be designated a **"school official" with a legitimate educational interest**
under FERPA where applicable.

**11.2 Prohibited uses.** Consultant shall not: (a) use MIT Data to train, fine-tune, or evaluate any
model for any purpose other than performing the Services for MIT; (b) sell or share MIT Data; or
(c) use MIT Data for advertising or profiling.

**11.3 No student work to remote providers without authorization.** Implementing Design Document R31
and R4, Consultant shall not transmit real student work, teacher scores, or other Personal Data to
any remote inference or cloud provider **except** under a deployment MIT has explicitly authorized in
writing, and then only where zero-retention routing is configured and a data-processing agreement is
in place with that provider. **Development, CI, and demonstration work shall use synthetic or
expressly consented corpora only.** Consultant shall evidence compliance at each Gate.

**11.4 Edge profile.** In the `edge-local` deployment, student work and all intermediate artifacts
shall remain on the deployed machine and shall not traverse any network service in the critical path
(R1, R4).

**11.5 Consents.** MIT is responsible for obtaining all student, parent, teacher, and institutional
consents and notices required in each jurisdiction where the Platform is deployed, including any
required under FERPA, applicable state law, and the law of any country where a Participating School
is located.

**11.6 Security.** Consultant shall apply encryption in transit and at rest for MIT Data, access
control on a need-to-know basis, and secure deletion. Consultant shall notify MIT **without undue
delay and in any event within seventy-two (72) hours** of becoming aware of any unauthorized access
to or disclosure of MIT Data, and shall cooperate with MIT's response.

**11.7 Retention and return.** On MIT's request, and in any event on termination, Consultant shall
return or securely destroy all MIT Data and certify destruction, excepting de-identified telemetry
permitted under Section 8.7 and copies required by law.

**11.8 Exemplars.** Anchor exemplars derived from real student work shall follow Design Document
§9.4: real verbatim exemplars may be used **within the originating institution only** and are blocked
from export; exported packages carry paraphrased or synthetic exemplars with teacher approval.

**11.9 Human subjects.** MIT is solely responsible for determining whether any activity constitutes
human-subjects research and for obtaining MIT COUHES (IRB) approval and any equivalent foreign
approvals. Consultant shall cooperate with, and comply with the conditions of, any approved protocol.

---

## ARTICLE 12 — CHANGE CONTROL

**12.1** Any change to scope, Deliverables, Acceptance Criteria, schedule, or fees requires a written
**Change Order** signed by both parties, stating the change, its schedule effect, and its price
effect.

**12.2** Consultant shall not be obliged to perform work outside Schedule A. Consultant shall not be
deemed in breach for declining unpriced additional work.

**12.3** Changes are priced at the daily rate in Schedule B Section B.4 unless otherwise agreed.

**12.4 Design evolution.** Where implementation experience shows a Design Document requirement to be
technically unsound or materially more costly than assumed, Consultant shall notify MIT with a
written recommendation. Agreed changes to the architecture are recorded by Change Order and reflected
in the Acceptance Criteria.

---

## ARTICLE 13 — WARRANTIES, DISCLAIMERS, AND REMEDIES

**13.1 Consultant warranties.** Consultant warrants that:

**(a)** the Services will be performed in a professional and workmanlike manner by suitably skilled
personnel;

**(b)** for **ninety (90) days** after acceptance of each Gate, the Deliverables will conform in
material respects to their Acceptance Criteria and accompanying documentation; Consultant's sole
obligation and MIT's exclusive remedy for breach of this warranty is correction of the non-conformity
at Consultant's cost, or, failing correction after a reasonable opportunity, refund of the tranche
paid for that Gate;

**(c)** to Consultant's knowledge, the Platform as delivered does not infringe the IP rights of any
third party; and

**(d)** the Deliverables will not knowingly contain malicious code.

**13.2 Disclaimer specific to automated assessment.** MIT acknowledges, consistent with Design
Document §0.5, §7.9, and Article 11 thereof, that:

**(a)** the Platform is **formative decision support**. It does not warrant that any grade, score, or
narrative feedback it produces is correct;

**(b)** **the teacher remains accountable for every grade**, retains authority to change any score at
any time, and is the marker of record;

**(c)** the Platform is designed to issue grades that no human has reviewed, marked as provisional,
and MIT accepts that design characteristic as a deliberate and disclosed property of the system;

**(d)** performance degrades on ambiguous, partial-credit responses, and on poor-quality scans and
difficult handwriting; and

**(e)** validation statistics are population-scoped and backend-scoped (Design Document R23, R30) and
do not transfer automatically to a different cohort, language of instruction, assessment type,
hardware profile, or model quantization.

**13.3 Remedy on failed Gate.** If Consultant fails an Acceptance Criterion after two cure cycles
under Section 4.4, MIT may, at its election: (a) accept the Deliverable with an agreed fee reduction;
(b) issue a Change Order relaxing the criterion; or (c) terminate under Section 14.3, in which case
MIT pays for all previously accepted Gates and retains the license in Section 8.3 as to those Gates.

**13.4 Feasibility risk is shared, and its allocation is stated.** Where a Gate G5 or G6 measurement
demonstrates that a requirement of the Design Document is **not achievable on the agreed hardware or
within the agreed batch window** despite Consultant's professional performance, that outcome is a
finding, not a breach. The parties shall meet within fifteen (15) business days and either revise the
criterion by Change Order or terminate under Section 14.2, with Consultant paid for all Gates
accepted and for work in progress on the current Gate on a pro-rata basis.

**13.5 EXCEPT AS EXPRESSLY STATED IN THIS ARTICLE, THE PLATFORM AND SERVICES ARE PROVIDED WITHOUT
WARRANTY OF ANY KIND, AND EACH PARTY DISCLAIMS ALL IMPLIED WARRANTIES INCLUDING MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE, AND NON-INFRINGEMENT.**

---

## ARTICLE 14 — TERM AND TERMINATION

**14.1 Term.** This Agreement commences on the Effective Date and continues until Final Acceptance at
Gate G7 or earlier termination.

**14.2 Termination for convenience by MIT.** MIT may terminate on **thirty (30) days'** written
notice. MIT shall pay: (a) all tranches for accepted Gates; and (b) for work in progress on the
current Gate, a pro-rata amount reflecting the percentage of that Gate's Acceptance Criteria then
demonstrably met, as evidenced by Consultant's records and reasonably agreed.

**14.3 Termination for cause.** Either party may terminate on thirty (30) days' written notice of a
material breach not cured within that period.

**14.4 Effect on license.** Termination for any reason does **not** affect MIT's license under
Section 8.3 as to Deliverables accepted before termination, provided MIT has paid the corresponding
tranches. Termination by Consultant for MIT's non-payment suspends the license until payment is made.

**14.5 Survival.** Articles 1, 8, 9, 10, 11, 13, 14.4, 15, 16, 17, and 20 survive.

---

## ARTICLE 15 — USE OF NAMES

**15.1** Neither party shall use the name, trademarks, logos, or the name of any employee of the
other in any advertising, press release, or promotional material without prior written permission,
which shall not be unreasonably withheld. In no event may Consultant use the name "Massachusetts
Institute of Technology," "MIT," or "MIT Center for International Studies" in a manner suggesting
MIT's endorsement of a commercial product.

**15.2** Notwithstanding Section 15.1, Consultant may identify MIT as a client in factual client
lists and in response to due-diligence inquiries, and each party may make factual statements required
by Article 9 or by law.

---

## ARTICLE 16 — INDEMNIFICATION AND LIABILITY

**16.1 Consultant IP indemnity.** Consultant shall defend and indemnify MIT against third-party
claims that the Platform as delivered infringes a United States copyright, patent, or trade secret,
and shall pay damages finally awarded, provided MIT gives prompt notice, tenders control of the
defense, and cooperates. Consultant may procure the right to continue use, replace, or modify the
Platform to make it non-infringing. This indemnity excludes claims arising from MIT Data, MIT
modifications, use outside the license, or combination with materials not supplied by Consultant.

**16.2 MIT indemnity.** MIT shall indemnify Consultant against third-party claims arising from
MIT Data, from MIT's failure to obtain consents under Section 11.5 or approvals under Section 11.9,
or from MIT's use of the Platform outside the scope of the license, except to the extent caused by
Consultant's breach or negligence.

**16.3 Limitation.** EXCEPT FOR THE CARVE-OUTS IN SECTION 16.4, EACH PARTY'S TOTAL AGGREGATE
LIABILITY UNDER THIS AGREEMENT SHALL NOT EXCEED THE TOTAL FEES PAID OR PAYABLE UNDER SCHEDULE B, AND
NEITHER PARTY SHALL BE LIABLE FOR INDIRECT, INCIDENTAL, CONSEQUENTIAL, SPECIAL, OR PUNITIVE DAMAGES
OR FOR LOST PROFITS, HOWEVER CAUSED.

**16.4 Carve-outs.** Section 16.3 does not limit: (a) Consultant's obligations under Section 16.1;
(b) either party's breach of Article 10 or Article 11; (c) either party's gross negligence or willful
misconduct; or (d) MIT's payment obligations.

**16.5 Insurance.** Consultant shall maintain, at its expense, throughout the Term and for two years
thereafter: commercial general liability of not less than **US $1,000,000** per occurrence /
**$2,000,000** aggregate; professional liability (errors and omissions) of not less than
**US $1,000,000** per claim; and cyber liability of not less than **US $1,000,000** per claim.
Consultant shall furnish certificates naming MIT as additional insured on the general liability
policy on request.

---

## ARTICLE 17 — COMPLIANCE

**17.1 Independent contractor.** Consultant is an independent contractor. Nothing creates an
employment, partnership, agency, or joint-venture relationship. Consultant is responsible for its own
taxes, benefits, and insurance and is not eligible for MIT employee benefits. **Consultant determines
its own working hours, location, tools, and methods** (Sections 2.6 and 3.2), engages in other
professional activity concurrently (Section 17.4), and is engaged for the delivered and accepted
result rather than for time worked.

**17.2 Export control.** The parties acknowledge that the Program operates internationally.
Consultant shall comply with U.S. export control laws (EAR, ITAR, OFAC sanctions). **MIT represents
that it will not furnish Consultant with export-controlled technical data** and shall identify in
advance any Participating School located in a sanctioned or embargoed jurisdiction. Neither party is
obliged to perform an act that would violate export control or sanctions law, and any resulting delay
extends the schedule day-for-day.

**17.3 Non-discrimination and conduct.** Consultant shall comply with applicable non-discrimination
laws and, while on MIT premises or at a Participating School, with the applicable institutional
policies made known to it.

**17.4 Conflicts.** Consultant represents that performance of the Services does not conflict with any
obligation to a third party. Consultant may serve other clients, including in the education sector,
provided it complies with Articles 10 and 11.

---

## ARTICLE 18 — FORCE MAJEURE

Neither party is liable for delay or failure caused by events beyond its reasonable control,
including natural disaster, war, epidemic, governmental action, failure of a third-party inference
provider, or loss of connectivity at a Participating School, provided the affected party gives prompt
notice and uses reasonable efforts to mitigate. Schedules extend accordingly.

---

## ARTICLE 19 — DISPUTE RESOLUTION

**19.1 Escalation.** The parties shall first attempt resolution by good-faith negotiation between the
technical lead and MIT's program director within fifteen (15) business days of written notice, and
thereafter between senior representatives within a further fifteen (15) business days.

**19.2 Mediation.** Unresolved disputes shall be submitted to non-binding mediation in Boston,
Massachusetts, before a mediator agreed by the parties, with costs shared equally.

**19.3 Forum.** If mediation does not resolve the dispute within sixty (60) days, either party may
bring suit in the state or federal courts located in Suffolk or Middlesex County, Massachusetts, to
whose exclusive jurisdiction the parties consent.

**19.4 Continued performance.** Except where the dispute concerns non-payment, both parties shall
continue performance during dispute resolution.

---

## ARTICLE 20 — GENERAL

**20.1 Governing law.** This Agreement is governed by the laws of the Commonwealth of Massachusetts,
without regard to conflict-of-laws rules. The U.N. Convention on Contracts for the International Sale
of Goods does not apply.

**20.2 Assignment.** Neither party may assign this Agreement without the other's written consent,
except that Consultant may assign to a successor entity of its business (including an incorporated
successor to Agentic Consulting) on written notice, provided the successor assumes all obligations.

**20.3 Notices.** Notices shall be in writing to the addresses on the signature page, by email with
confirmed receipt or by courier, effective on receipt.

**20.4 Severability.** If any provision is held unenforceable, the remainder continues in effect and
the provision is reformed to the minimum extent necessary.

**20.5 Waiver.** No waiver is effective unless in writing; no single waiver is a continuing waiver.

**20.6 Amendment.** This Agreement may be amended only by a writing signed by both parties.

**20.7 Counterparts.** This Agreement may be executed in counterparts, including electronically.

**20.8 Schedules.** Schedules A, B, C, and D are incorporated by reference.

**20.9 Entire agreement and order of precedence.** This Agreement is the entire agreement and
supersedes all prior understandings. In the event of conflict, the order of precedence is:
(1) this Agreement; (2) Schedules A, B, D; (3) an executed Joint Development Addendum (Schedule C) as
to its defined field only; (4) an executed Change Order. **Pre-printed terms on any purchase order,
invoice, portal, or click-through are of no effect, and MIT's issuance of a purchase order referencing
this Agreement does not incorporate those terms.**

---

## SIGNATURES

**AGENTIC CONSULTING**

Signature: ______________________________
Name: **Emmanuel Cohen-Yashar**
Title: Principal
Date: ______________
Email: manu.cohenyashar@gmail.com
Address: [ADDRESS]

**MASSACHUSETTS INSTITUTE OF TECHNOLOGY**
*acting through the Center for International Studies*

Signature: ______________________________
Name: ______________________________
Title: ______________________________
Date: ______________
Address: 1 Amherst Street, Cambridge, MA 02142

*Acknowledged for procurement / financial terms:*

Signature: ______________________________
Name: ______________________________
Title: ______________________________
Date: ______________

---
---

# SCHEDULE A — DELIVERABLES, GATES, AND ACCEPTANCE CRITERIA

Section references (§) and requirement identifiers (R#) are to the Design Document.

**Assumed cohort scale for all acceptance tests:** 350 submissions, approximately 4 pages each,
predominantly handwritten and scanned, mixed format (open questions plus multiple-choice items).

---

### Gate G0 — Mobilization and Project Baseline
**Target: Effective Date + 2 weeks**

**Deliverables**
1. Project plan with the Gate schedule, dependencies, and MIT responsibilities.
2. Requirements traceability matrix mapping every requirement R1–R60 to a Gate.
3. Development environment, repository, and CI pipeline in MIT-accessible form.
4. Pass-Through account setup per Article 7 and Schedule D.
5. Synthetic and consented test corpus plan (Section 11.3), including sourcing of real scanned
   handwriting fixtures spanning legible to marginal.

**Acceptance Criteria**
- A1. Traceability matrix accounts for every requirement R1–R60 with a Gate assignment or an express
  "out of scope" entry agreed by MIT.
- A2. CI pipeline builds and runs in a Linux container with all model calls served by the hosted
  provider (R28).
- A3. The MIT-held inference (OpenRouter or equivalent) account is operational and accessible to
  Consultant with a spend limit set, or Section 7.3 reimbursement is agreed.

---

### Gate G1 — Foundations: Provider Abstraction, Persistence, and Audit
**Target: G0 + 4 weeks**

**Deliverables**
1. Provider abstraction with three interchangeable implementations: hosted (OpenRouter), local, and
   recorded-fixture (R27, §12).
2. Persistence layer Tier 0 with the work ledger, evidence and verdict stores, and the audit record
   (§9).
3. Content-hash work identifiers and idempotent re-run (R14, §9.10).
4. Version pinning of every model, build, quantization, prompt template, and rubric version (§6.7).
5. Backend-scoped validation record schema (R30).

**Acceptance Criteria**
- A4. **No backend-specific code path exists in any pipeline stage** (R27), demonstrated by static
  analysis and by running the identical test suite against all three providers.
- A5. A run killed at an arbitrary point resumes without duplicated or lost work, verified over at
  least three kill points (R14, R3).
- A6. Every stored score carries rubric version, panel composition, member versions, backend,
  quantization, and confidence threshold in force (§6.7).
- A7. Validation records cannot be written without a population scope; **no global "validated" flag
  exists in the schema** (R23).

---

### Gate G2 — Ingestion, Transcription, and the Validation Ladder
**Target: G1 + 6 weeks** — *the highest-risk Gate*

**Deliverables**
1. PDF-to-Markdown ingestion module for **all four artifact kinds** — assessment, reference solution,
   rubric, submissions — typed or handwritten (§7.7, R38).
2. Deterministic multi-file assembly with per-page provenance, duplicate-page and sequence-gap
   detection (R33).
3. Canonical, content-hashed, immutable Markdown artifact with versioning and dependent-work
   invalidation (R32).
4. Structured descriptions of non-text regions — diagrams, graphs, aligned tables, selection marks,
   struck-through and superseding work (R45, R47), with the describe-never-evaluate constraint
   enforced in prompt template and tests (R46).
5. Validation ladder gates V0–V4, including the wrong-test gate with three-valued outcome and the
   high-failure-rate circuit breaker (R34, R35, R36).
6. Operator triage/quarantine queue, separate from the teacher review queue.
7. Differential text-layer cross-check on pages carrying an embedded text layer.

**Acceptance Criteria**
- A8. **No stage downstream of ingestion receives a PDF or a page image**, verified by interface
  contract and test (R38).
- A9. Transcription quality measured on the real scanned-handwriting fixture set, reported by
  legibility band, with the measured figures recorded in the Gate Report. *No fixed accuracy
  threshold applies at this Gate; the measurement is the deliverable and the figures inform the G5
  and G6 criteria set by Change Order if needed.*
- A10. On a seeded corpus: every missing page, duplicated page, unreadable file, unmatched student
  identity, and wrong-test submission is **quarantined and never expressed as a score** (R34).
- A11. Wrong-test detection: on a seeded mixed pile, `mismatch` and `uncertain` both halt scoring and
  route to a human; **no submission is auto-reassigned** (R35).
- A12. Absent, blank, and present content are represented distinctly in region metadata (R36),
  verified by test.
- A13. An evaluative word list (correct, valid, appropriate, properly, should) does not appear in
  generated region descriptions across the fixture corpus (R46).
- A14. Divergence between an embedded text layer and the transcription on a **reference solution** is
  a hard stop.

---

### Gate G3 — Scoring Engine: Extraction, Isolation, Panel, and Routing
**Target: G2 + 6 weeks**

**Deliverables**
1. Criterion decomposability classification (`atomic` / `atomic_with_gate` / `holistic`) with teacher
   confirmation and schema lock (R49, R50, §5.3).
2. Sweep 1 extraction, batched by (question, criterion), in topological order over the dependency
   graph (§8.4).
3. Evidence integrity gate: span offset verification, required-evidence check, OCR-overlap impact
   routing, second-family extraction on high-risk criteria (R19, R24, §7.4, §7.5).
4. Judgment isolation boundary (§7.2 Rules 1–3), with synthesis structurally unable to write scores.
5. Sweep 2 band scoring: closed criterion-specific band sets, behaviourally anchored descriptors,
   evidence-first field ordering, no numeric value in any judge prompt or output
   (R39, R40, R42, §5.10).
6. Odd-panel aggregation on the ordinal band scale, band→points mapping applied once after
   aggregation, ordinal Krippendorff's α (R41, R48).
7. Deterministic evaluator for multiple-choice criteria with answer-key lookup, ambiguous/multiple/
   unreadable mark handling routed to the operator (R52–R55, §7.8).
8. Confidence routing with confidence inversion on evidence-integrity failure, plus the random
   escalation arm (§5.8, §7.1, §7.4).

**Acceptance Criteria**
- A15. **No point value, `max_points`, or numeric scale appears in any judge prompt or judge output**
  (R39), verified by prompt lint over the full template set.
- A16. Response schema field order is `cited_spans` → `evidence_assessment` → `evidence_sufficient` →
  `band` → `self_confidence`, enforced by schema and lint (R42).
- A17. `judge_count` admits only 0, 1, 3, 5; an even panel is a write that fails (R48).
- A18. No prior verdict, prior student, or conversation history crosses the isolation boundary,
  verified by request-capture inspection over a full run (§7.2 Rule 1).
- A19. Synthesis output contains no writable score field and no numeric or holistic quality claim,
  verified by schema and by an automated assertion over generated narratives (§7.2 Rule 3, §10).
- A20. Averaging of band-derived points is impossible by construction (R41).
- A21. Deterministic-item correctness is excluded from every agreement, κ, and grader-quality figure
  by data model, not convention (R53).
- A22. An unresolvable selection mark is never resolved to an option and never scored incorrect;
  it routes to the operator queue, not the teacher queue (R54, R55).

---

### Gate G4 — Grade Policy, Teacher and Operator Surfaces, Assessment Package
**Target: G3 + 6 weeks**

**Deliverables**
1. Declarative grade policy engine — weighted sums, gates, drop-lowest / best-k-of-n, scaling,
   rounding, and a grade boundary table — expressible as data, never as script (R57, R59, §7.9).
2. Plain-language rendering of the grade policy for teacher approval, and the default policy that
   applies when the teacher declares nothing.
3. Setup flow: question inventory confirmation, answer-key entry, rubric-reading approval,
   decomposability confirmation, grade policy declaration.
4. Teacher review queue **budgeted in teacher-minutes** and ranked by expected value, with reserved
   carve-outs for the blind sample and random arm, and explicit disclosure of the unsurfaced residual
   (R12, R26, §10).
5. Group/batch review action for identical patterns across many students.
6. Provisional-grade handling: labelled, never withheld; range display where a provisional item could
   cross a boundary; automatic finalization on run completion or review-window lapse (R26, R58, R60).
7. Blind sample and whole-grade sample workflows (R21, §7.9).
8. Per-student output: criterion narrative first, cited evidence spans, secondary editable score,
   confidence flag, rubric version. Image crop retained and one-click viewable where evidence lies in
   a described region (R46).
9. Class-level rollup: per-criterion distribution, misconception clusters, MCQ distractor analysis,
   chance-corrected agreement with sample size attached.
10. Assessment Package export and import as a **single self-contained file**, with exemplar
    provenance enforcement and cumulative, population-scoped validation record
    (R16, R17, R18, R23, §9.4).
11. Operator surface: quarantine and transcription triage, distinct from the teacher queue.

**Acceptance Criteria**
- A23. Every submission in a full test run receives a complete final grade with **no per-student
  teacher action** (R56).
- A24. Setup blocks on exactly two items — question inventory and MCQ answer keys — and on nothing
  else; every other touchpoint has a working default (R60), verified against the §7.9 touchpoint
  table.
- A25. The review queue fills a teacher-specified minute budget and states the residual explicitly
  ("these are the N highest-value items of M flagged") (R12, §10).
- A26. The residual is neither silently finalized nor backfilled with any substitute value such as a
  cohort mean (R26).
- A27. Editing the grade boundary table or the band→points mapping is subject to the schema lock and
  version pin, and is not available as an unlogged edit (R43, R59, §6.2).
- A28. A package exported to a file and imported on a clean installation reproduces identical grades
  from identical inputs (R16, R17).
- A29. A package loaded into a population with no validation record displays "no validation data for
  this population," not a figure from elsewhere (R23).
- A30. The dashboard contains **no unqualified single accuracy percentage** anywhere (R8, §10).

---

### Gate G5 — Cloud Feasibility Pilot *(feasibility gate)*
**Target: G4 + 4 weeks**

**Deliverables**
1. End-to-end run of the `cloud-hosted` profile on the largest real cohort MIT is able to supply
   under dependency D4 and Article 11, with a mixed-format paper. **The target is 250 or more
   submissions.** Where MIT supplies fewer, the Gate proceeds on what is supplied and the Feasibility
   Report states the actual n against every figure (Section 4.6); a shortfall in MIT-supplied data is
   never a ground for withholding acceptance (Section 4.5).
1a. A separate throughput run at approximately 350 submissions on the scaled corpus of Section 2.8(b),
   to establish the `cloud-hosted` baseline against which Gate G6 measures the `edge-local` profile.
2. Feasibility Report covering: wall clock; cost per assessment against the configured ceiling;
   ingestion failure and operator-triage rates; teacher-minutes actually consumed; per-criterion
   chance-corrected agreement against the blind sample with sample size; separate reporting of judged
   and deterministic items; the score-compression check (R44); and the surface-proxy regression
   against length, vocabulary complexity, OCR quality and legibility band (§6.9).
3. Behaviour-under-outage evidence: a mid-run provider failure exercised and recovered (§8.7).

**Acceptance Criteria**
- A31. **The zero-touch test passes.** A run started with no subsequent teacher input completes,
  finalizes, and delivers a complete grade for every submission (R60). *This is the single most
  important acceptance criterion in the Agreement.*
- A32. Every submission has either a complete grade or a specifically named ingestion failure routed
  to the operator; no submission is silently absent.
- A33. Per-run cost is estimated before dispatch and enforced against the configured ceiling (R5).
- A34. The Feasibility Report presents chance-corrected agreement, scoped to assessment type and
  backend, with sample size attached, and does not merge atomic with holistic criteria (R51) or
  judged with deterministic items (R53).
- A35. Teacher time consumed in setup and in one review session is measured and reported against the
  R9 budget of minutes rather than hours.
- A36. A mid-run provider outage does not corrupt the working store; the run resumes and completes.

> **Note.** A31–A33 and A36 are pass/fail. The statistical figures at A34–A35 are **measured and
> reported**, not gated on a threshold, because a threshold set before measurement would be a
> guess. Where MIT wishes to convert a measured figure into a threshold for G7, it does so by Change
> Order under Section 12.1 after seeing the G5 numbers.

---

### Gate G6 — Edge Deployment on Apple Silicon and Hardware Acceptance Test *(feasibility gate)*
**Target: G5 + 4 weeks; requires MIT-Furnished Equipment delivered under Section 7.6**

**Deliverables**
1. `edge-local` deployment on the MIT-Furnished Equipment (Section 7.6), with hardware profile,
   quantization target, and concurrency ceiling recorded in configuration (§8.1).
2. Full §8.5 hardware acceptance test on **approximately 350 representative submissions in the
   actual medium** — the scaled corpus of Section 2.8(b) — with the real transcription stage, actual
   models at actual quantization, actual serving stack and concurrency, persistence to the actual
   storage medium, and one deliberate mid-run kill.
3. §8.7 backend conformance suite run against identical fixtures on both the local and hosted
   backends, with divergence reported.
4. Hardware Acceptance Report against the full §8.5 metric table.

**Acceptance Criteria**
- A37. The run completes **fully offline**, with no network service in the critical path, and does not
  fail over to a different backend mid-run (R1).
- A38. Student work and all intermediate artifacts remain on the machine (R4).
- A39. Wall clock from ingestion through synthesis **fits an overnight batch window with margin**, on
  the agreed hardware, for 350 submissions (R10). The agreed window is **[12] hours** unless amended
  by Change Order.
- A40. Peak memory stays under the profile ceiling at target concurrency; no out-of-memory failure.
- A41. Resume after the deliberate kill is correct — no duplicated and no lost work.
- A42. Every remaining §8.5 metric — achieved throughput, prefix cache hit rate, model swap time and
  count, thermal sustain, OCR failure and triage rate, failure and retry rate, disk growth — is
  measured and recorded in the Report.
- A43. Backend divergence between local and hosted builds is measured and reported, and validation
  records are correctly scoped to backend, build, and quantization (R30).

> **Note.** Per Sections 7.7 and 13.4, if A39, A40, or the thermal-sustain element of A42 cannot be
> met on the supplied laptop despite Consultant's professional performance, the parties shall revise
> the hardware profile, the batch window, the panel configuration, or the chassis by Change Order
> rather than treat the result as a breach. Laptop thermal throttling under a multi-hour sustained
> load is the specific risk this note exists to allocate.

---

### Gate G7 — Final Acceptance, Documentation, Training, and Handover
**Target: G6 + 4 weeks**

**Deliverables**
1. Complete source code, build scripts, deployment runbook, and configuration reference.
2. Operator manual (scanning, quarantine triage, rescans) and teacher guide in plain language.
3. Two training sessions: one for MIT program staff and operators, one for participating teachers.
4. Bill of materials for all third-party and open-source components and model weights, with licenses
   and pinned versions (Section 8.9).
5. Known-limitations register, drawn from Design Document §11 and from findings at G5 and G6.
6. Handover of all Pass-Through hardware to MIT's custody.

**Acceptance Criteria**
- A44. **A complete, unassisted end-to-end run performed by MIT personnel on MIT hardware**, from
  scanned PDFs to delivered grades, with Consultant present only as an observer.
- A45. The zero-touch test (A31) passes on the `edge-local` profile.
- A46. Documentation is sufficient for MIT personnel to run a new assessment, from package setup to
  grade delivery, without contacting Consultant.
- A47. All Gate G1–G6 Acceptance Criteria remain satisfied on the final build (no regression).

**On acceptance of G7, the final 10% tranche becomes payable.**

---

### MIT Dependencies (delay to any of these extends the affected schedule day-for-day)

| # | MIT responsibility | Needed by |
|---|---|---|
| D1 | MIT-held inference (OpenRouter) account operational, Consultant granted access | G0 |
| D2 | Real scanned-handwriting fixtures, consented, spanning legible to marginal; may be small | G2 |
| D3 | Named teacher(s) available for setup, elicitation, and blind sample | G4 |
| D4 | Largest available real cohort (target ≥250 submissions), with consents and COUHES approval as applicable. Consultant assembles the scaled throughput corpus itself under Section 2.8(b) | G5 |
| D5 | MIT-Furnished Equipment (Section 7.6) delivered to Consultant | G6 |
| D6 | MIT personnel available for training and the unassisted run | G7 |

---
---

# SCHEDULE B — FEES AND PAYMENT

## B.1 Fixed Fee

**US $135,000**, exclusive only of hosted inference (token) charges under Article 7 and Schedule D.
No equipment cost and no travel allowance form part of this Agreement: MIT furnishes the Mac hardware
from a source of its own choosing (Section 7.6), and Consultant absorbs all local travel (Section 6.1).

**This is a package price for a delivered result.** It is not derived from an hourly or daily rate,
and it is not adjustable by reference to time spent or to Consultant's method of production
(Section 2.6). It reflects the complexity and the value of the delivered system: a validated,
auditable grading harness that makes constructed-response assessment feasible at 150–350 students per
class, delivered with a perpetual institutional license (Section 8.3) rather than as work for hire.

## B.2 Payment schedule

| Gate | Description | Target | % | Amount (USD) | Cumulative |
|---|---|---|---:|---:|---:|
| **G0** | Mobilization and project baseline | wk 2 | 8% | $10,800 | $10,800 |
| **G1** | Foundations: provider abstraction, persistence, audit | wk 6 | 10% | $13,500 | $24,300 |
| **G2** | Ingestion, transcription, validation ladder | wk 12 | 16% | $21,600 | $45,900 |
| **G3** | Scoring engine: extraction, isolation, panel, routing | wk 18 | 16% | $21,600 | $67,500 |
| **G4** | Grade policy, teacher/operator surfaces, package | wk 24 | 14% | $18,900 | $86,400 |
| **G5** | **Cloud feasibility pilot** (largest available real cohort) | wk 28 | 14% | $18,900 | $105,300 |
| **G6** | **Mac deployment + §8.5 hardware acceptance** | wk 32 | 12% | $16,200 | $121,500 |
| **G7** | **Final acceptance, training, handover** | wk 36 | **10%** | **$13,500** | **$135,000** |
| | **TOTAL** | | **100%** | **$135,000** | |

**Rationale for this shape.** Ninety percent of the Fixed Fee is earned progressively against
independently valuable, objectively testable increments, so that a substantial development effort
undertaken before any working system exists is compensated as it is delivered. The final ten percent
is contingent on a demonstrably working end-to-end system operated **unassisted by MIT personnel**
(Gate G7, criterion A44). That is MIT's protection against paying in full for something that does not
work, and it is the reason the earlier tranches are not further conditioned.

## B.3 Indicative schedule

Approximately **thirty-six (36) weeks**, or eight to nine months, from the Effective Date to Gate G7,
assuming MIT dependencies D1–D6 are met on time.

**These are planning estimates, not deadlines.** Per Section 3.2, Consultant controls the timing of
its work and does not undertake to devote any particular number of hours. The parties' sole schedule
remedy is the twelve-month long-stop date in Section 3.4. Gate target dates are refined by the
project plan delivered at G0 and are not thereafter binding.

## B.4 Rates for change orders, support, and travel

These rates apply **only** to work outside Schedule A. They do not convert the Fixed Fee into a
time-based engagement.

| Item | Rate |
|---|---|
| Additional work under a Change Order | **US $1,800 per day** (8 hours), or $250 per hour for part-days |
| Post-acceptance support and maintenance (optional) | **US $7,500 per quarter**, covering up to 3 days per quarter of corrective maintenance, dependency and model-version updates, and remote assistance |
| Post-acceptance support on demand (alternative to the retainer) | **US $250 per hour**, minimum 4-hour block |
| Travel time beyond one working day each way | 50% of the daily rate |
| Additional Participating School deployment (beyond the first) | **US $9,000** fixed per site, plus travel |
| Additional teacher/operator training session | **US $1,500** per session |

## B.5 Descope option

If MIT's available budget does not reach the Fixed Fee, the parties shall descope rather than
discount. The intended cut, in this order, is:

1. **Gate G4 calibration and elicitation workflow** (Design Document §6.4 ambiguity discovery and
   teacher-authored rubric revision) — **deduct US $16,000**. Design Document §12 expressly states
   that the system is "a complete, useful, defensible product" before anything in §6 exists, and that
   this capability should ship last. The grade policy, review queue, package, and all other G4
   deliverables remain in scope.
2. **Gate G7 second training session and the additional-site runbook** — **deduct US $4,000**.

Descoping is effected by Change Order under Article 12 before the affected Gate begins.

## B.6 Currency and method

All amounts are in United States Dollars, payable by bank transfer to an account nominated by
Consultant.

---
---

# SCHEDULE C — FORM OF JOINT DEVELOPMENT ADDENDUM

*(Template. Complete and execute **before** any collaborative work with an MIT laboratory begins,
per Section 8.5(b).)*

**Joint Development Addendum No. [__]** to the Software Development and License Agreement dated
[DATE] between Agentic Consulting and MIT.

**1. MIT Laboratory / Center:** ______________________________
**2. Principal Investigator:** ______________________________
**3. MIT Personnel covered:** ______________________________
**4. Consultant Personnel covered:** ______________________________

**5. Field of Collaboration** *(state narrowly; IP allocation under this Addendum applies only within
this field, and all work outside it remains governed by Sections 8.1–8.3)*:

> Example: *"Empirical evaluation and selection of judge-panel composition and prompt formulations
> for Hebrew- and Arabic-language constructed-response items, and the associated bias-measurement
> methodology. Excludes the ingestion module, the persistence layer, the grade policy engine, and the
> teacher and operator interfaces."*

**6. Contributions**

| Party | Personnel | Contribution | Funding source | Facilities used |
|---|---|---|---|---|
| Consultant | | | | |
| MIT | | | | |

**7. Start and end dates:** ______________________________

**8. IP allocation within the Field of Collaboration**

- **8.1** Inventions and works made **solely by Consultant Personnel**: owned solely by Consultant.
- **8.2** Inventions and works made **solely by MIT Personnel**: owned solely by MIT, administered by
  the MIT Technology Licensing Office.
- **8.3** Inventions and works made **jointly**: owned jointly in undivided shares of
  **Consultant [__]% / MIT [__]%** *(default 50/50 absent a stated split reflecting relative
  contribution)*. Each party may practice and license the joint IP without accounting to or consent
  of the other, subject to Section 8.5 below and to any pre-existing sponsor obligations disclosed
  here: ______________________________
- **8.4** Determination of inventorship follows United States patent law; determination of authorship
  follows United States copyright law. A disagreement on inventorship is referred to independent
  patent counsel agreed by the parties, whose determination is final as to inventorship only.
- **8.5** Each party grants the other a non-exclusive, royalty-free, worldwide license to practice
  the jointly owned IP **for internal research and educational purposes**, with no right to
  sublicense commercially without written agreement.
- **8.6** The Platform itself, and all Foreground IP outside the Field of Collaboration, remains
  solely owned by Consultant under Section 8.2 of the Agreement. **Integration of a Collaborative
  Invention into the Platform does not transfer any interest in the Platform.**

**9. Patent prosecution and costs**

- Lead party for filing: ______________________________
- Cost sharing: ______________________________
- A party declining to share costs on a given filing converts its interest in that filing to a
  non-exclusive, royalty-free license.

**10. Publication.** Article 9 of the Agreement applies. Authorship follows academic convention based
on intellectual contribution.

**11. Students and postdocs.** MIT confirms that participation is consistent with MIT policy on
student research, that no student's degree progress is contingent on Consultant's approval, and that
no student is subject to a publication restriction beyond Section 9.2.

**Signed for Agentic Consulting:** ____________________  Date: __________

**Signed for MIT:** ____________________  Date: __________

**Reviewed by MIT Technology Licensing Office:** ____________________  Date: __________

---
---

# SCHEDULE D — PASS-THROUGH COST BUDGET (borne by MIT, Article 7)

**There is exactly one Pass-Through Cost under this Agreement: hosted inference tokens.**

Two items that commonly appear in a budget of this kind are **deliberately absent**:

- **Equipment.** MIT furnishes the Mac hardware from a source of its own choosing under Section 7.6.
  Its cost is not a line item here, is not reimbursable, and is not Consultant's concern.
- **Travel.** Consultant is located in Andover, Massachusetts. Local attendance is included in the
  Fixed Fee under Section 6.1. No allowance is budgeted.

Consultant funds its own development equipment, cloud usage, CI, and tooling.

## D.1 Hosted inference (tokens)

**How the work actually consumes tokens.** Day-to-day development and functional testing run against
**a handful of submissions at a time** — the teacher-supplied dataset is small, and correctness is
established on small inputs. Full-cohort runs are reserved for stress testing and acceptance
measurement at Gates G3, G5, and G6. The recorded-fixture provider (Design Document §12) then lets
the majority of the regression suite re-run at **zero** token cost.

| Phase | What is actually run | Indicative cost |
|---|---|---|
| Gates G0–G4: development and functional testing | Small runs, typically 5–20 submissions. A 20-submission run is roughly 1,300 scoring calls plus ~80 vision page calls, on the order of **$1–3** | $400 – $900 |
| Gate G3 and G4 scale checks | A small number of full-cohort runs to exercise batching, resumability, and the working store | $150 – $350 |
| Gate G5 feasibility pilot | Real cohort supplied by MIT under dependency D4, run more than once, plus dual-scoring and the backend conformance suite | $300 – $700 |
| Gate G6 stress and acceptance test | The §8.5 acceptance run at full cohort scale, plus reruns after tuning. A full 350-submission run is roughly **$20–40** | $250 – $550 |
| Contingency | Model price changes, additional pilot reruns | $400 |
| **Total** | | **$1,500 – $2,900** |

**Not-to-exceed without written MIT approval: US $3,500.**

Consultant shall enforce a per-run cost ceiling (Design Document R5), report spend monthly, and
notify MIT before reaching 80% of this ceiling (Section 7.5).

## D.2 Total MIT out-of-pocket beyond the Fixed Fee

**Approximately US $1,500 – $2,900, capped at US $3,500.**

Plus MIT-Furnished Equipment obtained by MIT at its own cost and from its own source, which is not
priced in this Agreement.

---

*End of Agreement.*
