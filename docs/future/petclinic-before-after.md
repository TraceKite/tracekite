# Spring PetClinic before and after the Evidence Compiler

These examples apply the [Evidence Compiler proposal](evidence-compiler-strategy.md)
to the actual **Spring PetClinic Microservices** checkout in local TraceKite.
The project is a Spring Boot pet-clinic application, rather than a repository
named Pet Store.

The [shared verification design](../design/agent-verification-layer.md) now sets
the delivery order: verification first, optional context compilation later.
Before an edit, packets organize evidence; after an edit, the verifier checks
explicit structural claims against new inputs. Both use the same receipts.
The source observations below remain dated records, not a fresh ingestion.

**Before** describes the current source and stored graph, plus the work an agent
still has to do. **After** describes the proposed RWC behavior. RWC is not
implemented, no PetClinic files were changed, and no token or cost savings were
measured. The code changes below are hypothetical developer requests.

## Scope and evidence

- Repository: `spring-petclinic/spring-petclinic-microservices`.
- Clean source revision: `3858f9c630cf989bb6809a86edf47c2be78dc9f1`.
- Local checkout: `/app/data/repos/spring-petclinic_spring-petclinic-microservices`
  inside the TraceKite backend container.
- Source and local API reviewed on September 13 2026. The source revision agrees
  with the indexed repository metadata. The stored ingest is dated September 11;
  this review did not re-ingest it.
- The connected MCP `services()` response contained only an unrelated `adduce`
  graph. The PetClinic evidence instead comes from the local TraceKite HTTP
  instance and direct reads of the exact indexed source paths.

The local instance also contains **PetClinic Cloud**. Several service names are
shared between those two repositories. The examples below are scoped to
Microservices; they do not assert that the two deployments communicate.
These are cross-service examples inside one multi-module repository, not proof
of a multi-repository economic advantage.

The [stored observation](petclinic-evidence-observation.json) records the relevant
response subset, query and scope. Its counts are not an accuracy score. The
repository metadata reports 31 parse errors and 71 unparsed files out of 187
seen; those figures rule out treating a missing graph result as a universal
absence guarantee.

## Example 1 Rename the pet types endpoint

**Developer request:** "Rename `/petTypes` to `/pet-types` without missing the form
that uses it."

The graph returned the form-to-contract and provider-to-contract relationships,
and the cited source supports this particular connection:

| Evidence | Actual source |
| --- | --- |
| Browser request | [pet-form.controller.js line 8][pet-form] requests `api/customer/petTypes`. |
| Routing rule | [application.yml lines 33–38][customer-route] sends `/api/customer/**` to `lb://customers-service` and strips two path segments. |
| Provider route | [PetResource.java lines 49–51][pet-types] declares `GET /petTypes`. |

These are checked-in routing facts. The effective deployed configuration can
also come from the config server imported by `application.yml`; it was not
captured or exercised here.

| Before with current TraceKite | After with proposed RWC |
| --- | --- |
| An agent queries the graph, opens the form, routing rule and provider, and assembles the explanation. TraceKite already supplies useful source locations. | A typed endpoint-change packet supplies this evidence bundle, the proposed scope and explicit gaps. Exact source remains available for editing. |
| Another agent or a later session must reconstruct which pieces supported the earlier answer. | An authorized, unchanged snapshot can reuse the validated bundle. Reuse still incurs model input cost when text is sent. |
| Finding this form does not establish that every external caller is known. | The packet preserves that limit and asks for a compatibility decision or further caller evidence before removing the old endpoint. |

The requested code edit would include these two changes. They are illustrative,
not applied, and do not decide whether to retain a compatibility alias:

```diff
- @GetMapping("/petTypes")
+ @GetMapping("/pet-types")

- $http.get('api/customer/petTypes')
+ $http.get('api/customer/pet-types')
```

**What must be tested:** the changed provider route, the form's type loading,
gateway forwarding under the intended configuration, and the agreed behavior of
the old route. A smaller packet does not establish any of those results.

## Example 2 Change a gateway prefix without confusing direct clients

**Developer request:** "Change the public prefix from `/api/customer/**` to
`/api/customers/**`. Which code needs review?"

The checked-in gateway predicate is singular `customer`. The
[owner-list form][owner-list], [owner-edit form][owner-form], and
[pet form][pet-form] contain requests using that prefix. The indexed graph
supports representative connections from these files, although the pet-form
owner/pet distinction needs the correction discussed in Example 4.

By contrast, [CustomersServiceClient.java lines 35–39][customer-client] constructs
`http://customers-service/owners/{ownerId}`. It does not contain the public
`/api/customer` prefix. The current graph links that request to the
[owner provider route][owner-provider].

| Before with current TraceKite | After with proposed RWC |
| --- | --- |
| The agent compares routing YAML, JavaScript request paths and the direct Java client to distinguish public routing from service-to-service addressing. | The packet separates gateway-mediated requests from the direct client and cites the different derivations. |
| A cached explanation can remain superficially plausible after the YAML changes because the caller file did not change. | The gateway-rule guard invalidates dependent explanations even when the JavaScript bytes are unchanged. |
| Broad refresh repeats work for the direct client too. | Its relationship facts may remain reusable if their own dependencies and effective configuration remain valid. The packet envelope still records the new snapshot. |

The inference is conditional: changing only that gateway predicate does not
require a textual prefix replacement in this direct Java request. That is not a
claim that the whole client or deployment is unaffected. A route migration also
needs a deliberate old-prefix compatibility policy.

**What must be tested:** new and old public prefixes, representative forms, the
direct Java client's request, and effective config-server overrides. RWC must
not merge facts from the similarly named Cloud deployment to fill missing data.

## Example 3 A missing visits bridge must not become permission to delete

**Developer request:** "The graph does not show a code consumer for
`GET /pets/visits`. Can I remove it?"

The scoped bridge query returned 20 links and no `INVOKES` row for
`VisitsServiceClient.java`. The service-level trace returned a gateway
`ROUTES_TO` edge with no attached code crossings. Neither observation proves
that no caller exists.

Direct source inspection reveals the candidate the graph must account for:

- [VisitsServiceClient.java lines 34–45][visits-client] sets a default hostname
  and constructs a GET request to `pets/visits?petId={petId}`.
- [VisitResource.java lines 72–75][visits-provider] declares `GET pets/visits`
  and accepts a list-valued `petId` parameter.
- [VisitResourceTest.java lines 49–56][visits-provider-test] asserts the response
  to `/pets/visits?petId=111,222` in a controller test.
- [VisitsServiceClientIntegrationTest.java lines 26–44][visits-client-test]
  constructs this client with a mock server and invokes `getVisitsForPets`.

This is a **source-grounded candidate connection**, not an edge established by
the scoped bridge response or a runtime observation. The tests were read, not
executed. The client test checks a mocked response; it does not assert the
recorded outgoing request path or query parameters.

| Before with current TraceKite | After with proposed RWC |
| --- | --- |
| An empty code-crossing result requires manual follow-up and can be misread as absence. | An incomplete packet refuses a deletion conclusion and records the missing consumer-resolution obligation. |
| An agent may treat the presence of an integration test as sufficient validation. | The packet distinguishes a test file from an observed passing run, and distinguishes response assertions from request-contract assertions. |
| The unresolved hostname/path expression is not available as a verified graph fact. | RWC must request source expansion or improved extraction. It may assert the connection only after a supported resolver and source validation establish it. |

**What must be tested:** exact outgoing URL and comma-separated `petId` handling,
provider request/response compatibility, source-resolution coverage and any
remaining external callers. Deleting the endpoint is not justified by the
current result.

## Example 4 Reject a wrong pet update witness before caching it

This is an actual contradiction in the **stored graph**, not a hypothetical
future edit. The response pairs `pet-form.controller.js:43` with
`global:Http:customers-service:PUT:/owners/{}` at confidence score `0.88`, and
identifies the provider as `OwnerResource.java:85`.

The [cited JavaScript line][pet-update-client] constructs a longer path:

```javascript
$http.put("api/customer/owners/" + ownerId + "/pets/" + id, data)
```

The [owner-update mapping][owner-update-provider] is `PUT /owners/{ownerId}`.
The checked-in [pet-update mapping][pet-update-provider] is
`PUT /owners/*/pets/{petId}`. These are distinct request shapes. The stored
owner-update witness is not supported by its cited request.

There is a related citation problem: the graph's pet-form `GET /owners/{}`
entry cites line 15, which includes `/pets/` and a pet ID. A genuine owner-only
GET exists at line 21. Even when a file is a legitimate consumer, pointing to a
different request in that file is not an adequate receipt.

| Before in the stored graph | After required of a dependable RWC integration |
| --- | --- |
| The nested pet request is presented as an owner-update connection. | Refuse to certify that witness; retain the exact path mismatch as an unresolved diagnostic. |
| Content hashes and token-near-line checks could preserve the same mistake. | Compare the complete request expression and route semantics, with regression fixtures for concatenation and wildcard paths. |
| A repeated run of the same faulty extractor can reproduce the same answer. | Treat reproducibility as identity evidence, not semantic correctness. Fix and independently test extraction before accepting the corrected relationship. |

Do not claim that RWC alone fixes this issue. The stored ingest predates this
review, so a fresh ingestion is needed before attributing the failure to the
current extractor implementation. No extraction code or stored graph was
changed during this documentation task.

## A follow on test for newly added consumers

After resolving the extraction issues, introduce a new client of the existing
`/petTypes` route in a disposable test fixture. This is a proposed test, not a
claim that such a client currently exists.

**Before:** a cache that watches only the original form and provider sees no
changed supporting file and can reuse an incomplete consumer list.

**After:** the changed candidate set for the contract invalidates the result
list, while unchanged source evidence can be reused after validation. A full
snapshot invalidation baseline should also pass correctness; the experiment
asks whether selective invalidation saves meaningful work.

## Review findings and acceptance work

The strategy is suitable as a future research proposal after tightening snapshot
coherence, final serialized budgeting and unselected-candidate invalidation.
It is not an endorsement of current graph completeness or extraction accuracy.

| Document local ID | Required follow up | Evidence needed to close |
| --- | --- | --- |
| PET-RWC-01 | Investigate nested pet URL pairing and citations | Fresh ingest reproducer; complete-path regression cases; correct route pairing or explicit decline. |
| PET-RWC-02 | Investigate the missing visits client bridge | Fresh scoped query plus hostname/path resolution fixtures; supported source citations or an explicit unresolved state. |
| PET-RWC-03 | Add request-contract assertions for the visits client | A test checks the outgoing path and list-valued query, not only a mocked response body. |
| PET-RWC-04 | Measure actual before/after agent economics | Same tasks, source access, model and caching policy; all attempts and verification costs counted; quality assessed independently. |

These IDs are reference labels in this document, not additions or status changes
to `tasks.csv`. No saving percentage should be attached to these examples until
PET-RWC-04 is run.

## Reproduce the read only observations

With the local instance available on port 28080:

```sh
curl -fsS 'http://localhost:28080/api/repos'
curl -fsS 'http://localhost:28080/api/v2/code-bridges?repos=spring-petclinic_spring-petclinic-microservices&limit=100'
curl -fsS 'http://localhost:28080/api/v2/trace?from_service=api-gateway&to_service=visits-service&altitude=code&k=3'
```

The trace API is estate-wide and service names overlap, so use the scoped bridge
response and pinned Microservices source when drawing conclusions. Re-ingestion
or later code changes can legitimately change these dated observations.

[pet-form]: https://github.com/spring-petclinic/spring-petclinic-microservices/blob/3858f9c630cf989bb6809a86edf47c2be78dc9f1/spring-petclinic-api-gateway/src/main/resources/static/scripts/pet-form/pet-form.controller.js#L8
[customer-route]: https://github.com/spring-petclinic/spring-petclinic-microservices/blob/3858f9c630cf989bb6809a86edf47c2be78dc9f1/spring-petclinic-api-gateway/src/main/resources/application.yml#L33
[pet-types]: https://github.com/spring-petclinic/spring-petclinic-microservices/blob/3858f9c630cf989bb6809a86edf47c2be78dc9f1/spring-petclinic-customers-service/src/main/java/org/springframework/samples/petclinic/customers/web/PetResource.java#L49
[owner-list]: https://github.com/spring-petclinic/spring-petclinic-microservices/blob/3858f9c630cf989bb6809a86edf47c2be78dc9f1/spring-petclinic-api-gateway/src/main/resources/static/scripts/owner-list/owner-list.controller.js#L7
[owner-form]: https://github.com/spring-petclinic/spring-petclinic-microservices/blob/3858f9c630cf989bb6809a86edf47c2be78dc9f1/spring-petclinic-api-gateway/src/main/resources/static/scripts/owner-form/owner-form.controller.js#L12
[customer-client]: https://github.com/spring-petclinic/spring-petclinic-microservices/blob/3858f9c630cf989bb6809a86edf47c2be78dc9f1/spring-petclinic-api-gateway/src/main/java/org/springframework/samples/petclinic/api/application/CustomersServiceClient.java#L35
[owner-provider]: https://github.com/spring-petclinic/spring-petclinic-microservices/blob/3858f9c630cf989bb6809a86edf47c2be78dc9f1/spring-petclinic-customers-service/src/main/java/org/springframework/samples/petclinic/customers/web/OwnerResource.java#L67
[visits-client]: https://github.com/spring-petclinic/spring-petclinic-microservices/blob/3858f9c630cf989bb6809a86edf47c2be78dc9f1/spring-petclinic-api-gateway/src/main/java/org/springframework/samples/petclinic/api/application/VisitsServiceClient.java#L34
[visits-provider]: https://github.com/spring-petclinic/spring-petclinic-microservices/blob/3858f9c630cf989bb6809a86edf47c2be78dc9f1/spring-petclinic-visits-service/src/main/java/org/springframework/samples/petclinic/visits/web/VisitResource.java#L72
[visits-provider-test]: https://github.com/spring-petclinic/spring-petclinic-microservices/blob/3858f9c630cf989bb6809a86edf47c2be78dc9f1/spring-petclinic-visits-service/src/test/java/org/springframework/samples/petclinic/visits/web/VisitResourceTest.java#L49
[visits-client-test]: https://github.com/spring-petclinic/spring-petclinic-microservices/blob/3858f9c630cf989bb6809a86edf47c2be78dc9f1/spring-petclinic-api-gateway/src/test/java/org/springframework/samples/petclinic/api/application/VisitsServiceClientIntegrationTest.java#L26
[pet-update-client]: https://github.com/spring-petclinic/spring-petclinic-microservices/blob/3858f9c630cf989bb6809a86edf47c2be78dc9f1/spring-petclinic-api-gateway/src/main/resources/static/scripts/pet-form/pet-form.controller.js#L43
[owner-update-provider]: https://github.com/spring-petclinic/spring-petclinic-microservices/blob/3858f9c630cf989bb6809a86edf47c2be78dc9f1/spring-petclinic-customers-service/src/main/java/org/springframework/samples/petclinic/customers/web/OwnerResource.java#L83
[pet-update-provider]: https://github.com/spring-petclinic/spring-petclinic-microservices/blob/3858f9c630cf989bb6809a86edf47c2be78dc9f1/spring-petclinic-customers-service/src/main/java/org/springframework/samples/petclinic/customers/web/PetResource.java#L68
