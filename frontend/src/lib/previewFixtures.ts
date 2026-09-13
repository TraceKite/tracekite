/**
 * Fixture mode: `?preview=1` renders the real components against mock data.
 *
 * This exists so the UI can be reviewed visually without a live token. It
 * seeds CLIENT-side state only — it grants no API access, the backend still
 * rejects every unauthenticated request, and nothing here reaches the graph.
 * Shapes mirror the live payloads from /api/v2/service-map and /api/v2/trace
 * so what renders is what a real estate renders.
 */
import type {
  ServiceMapResponse, TraceResponse, RepoSummary, GraphNode, GraphLink, GraphStats,
} from "./types";

export function isPreviewMode(): boolean {
  if (typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).get("preview") === "1";
}

export const PREVIEW_REPOS: RepoSummary[] = [
  {
    id: "spring-petclinic_spring-petclinic-microservices",
    name: "spring-petclinic/spring-petclinic-microservices",
    owner: "spring-petclinic", repo: "spring-petclinic-microservices",
    github_url: "https://github.com/spring-petclinic/spring-petclinic-microservices",
    branch: "main", last_ingested_at: "2026-07-27T08:12:00Z",
    ingestion_status: "completed",
    source: "hosted",
    head_commit_sha: "6f1c2e9ab3d4f5061728394a5b6c7d8e9f0a1b2c",
    linked_at: "2026-07-27T08:13:00Z",
    claims_by_kind: {},
    parse_coverage: null,
    node_count: 1069, edge_count: 1642,
  },
  {
    id: "confluentinc_kafka-streams-examples",
    name: "confluentinc/kafka-streams-examples",
    owner: "confluentinc", repo: "kafka-streams-examples",
    github_url: "https://github.com/confluentinc/kafka-streams-examples",
    branch: "master", last_ingested_at: "2026-07-27T08:20:00Z",
    ingestion_status: "completed",
    source: "hosted",
    head_commit_sha: "aa11bb22cc33dd44ee55ff66aa77bb88cc99dd00",
    linked_at: "2026-07-27T08:21:00Z",
    claims_by_kind: {},
    parse_coverage: null,
    node_count: 1145, edge_count: 1301,
  },
];

const svc = (id: string, name: string, gateway = false) => ({
  id: `global:Service:${id}`, name, kind: "service" as const,
  is_gateway: gateway, repo_ids: ["spring-petclinic_spring-petclinic-microservices"],
});

export const PREVIEW_SERVICE_MAP: ServiceMapResponse = {
  nodes: [
    svc("api-gateway", "api-gateway", true),
    svc("customers-service", "customers-service"),
    svc("vets-service", "vets-service"),
    svc("visits-service", "visits-service"),
    svc("order-worker", "order-worker"),
    svc("shipping", "shipping"),
    { id: "global:Topic:kafka:order-events", name: "order-events", kind: "node" as const, scope: "kafka" },
    { id: "global:Topic:kafka:payments", name: "payments", kind: "node" as const, scope: "kafka" },
    { id: "global:SvcName:discovery:legacy-billing", name: "legacy-billing", kind: "service_name" as const, dead_end: true, scope: "discovery" },
  ] as any,
  edges: [
    { source: "global:Service:api-gateway", target: "global:Service:customers-service", type: "ROUTES_TO", confidence: 0.98, min_confidence: 0.98, max_confidence: 0.98, via: ["gateway_config"], weight: 1, path_prefix: "/api/customer", evidence: ["src/main/resources/application.yml:34"] },
    { source: "global:Service:api-gateway", target: "global:Service:vets-service", type: "ROUTES_TO", confidence: 0.98, min_confidence: 0.98, max_confidence: 0.98, via: ["gateway_config"], weight: 1, path_prefix: "/api/vet", evidence: ["src/main/resources/application.yml:41"] },
    { source: "global:Service:api-gateway", target: "global:Service:visits-service", type: "CALLS_SERVICE", confidence: 0.95, min_confidence: 0.85, max_confidence: 0.95, via: ["http"], weight: 4, path_prefix: null, evidence: ["src/api/apiClient.ts:88"] },
    { source: "global:Service:customers-service", target: "global:SvcName:discovery:legacy-billing", type: "CALLS_SERVICE", confidence: 0.72, min_confidence: 0.72, max_confidence: 0.72, via: ["http"], weight: 1, path_prefix: null, evidence: ["src/main/java/BillingClient.java:57"] },
    { source: "global:Service:order-worker", target: "global:Topic:kafka:order-events", type: "CONSUMES_FROM", confidence: 0.9, min_confidence: 0.9, max_confidence: 0.9, via: ["keda"], weight: 1, path_prefix: null, evidence: ["deploy/keda.yaml:12"] },
    { source: "global:Service:shipping", target: "global:Topic:kafka:order-events", type: "PUBLISHES_TO", confidence: 0.9, min_confidence: 0.9, max_confidence: 0.9, via: ["spring-kafka"], weight: 1, path_prefix: null, evidence: ["src/main/java/OrderPublisher.java:57"] },
    { source: "global:Service:customers-service", target: "global:Topic:kafka:payments", type: "PUBLISHES_TO", confidence: 0.85, min_confidence: 0.85, max_confidence: 0.85, via: ["spring-kafka"], weight: 1, path_prefix: null, evidence: ["src/main/java/PaymentPublisher.java:31"] },
    { source: "global:Topic:kafka:order-events", target: "global:Topic:kafka:payments", type: "FANS_OUT_TO", confidence: 0.95, min_confidence: 0.95, max_confidence: 0.95, via: ["terraform"], weight: 1, path_prefix: null, evidence: ["infra/main.tf:22"] },
  ] as any,
  totals: { services: 6, edges: 8 },
  truncated: false,
};

export const PREVIEW_TRACE: TraceResponse = {
  from: "global:Service:api-gateway",
  to: "global:Service:visits-service",
  altitude: "code",
  paths: [
    {
      nodes: [
        { id: "global:Service:api-gateway", name: "api-gateway", labels: ["Service", "Gateway"] },
        { id: "global:Service:customers-service", name: "customers-service", labels: ["Service"] },
        { id: "global:Service:visits-service", name: "visits-service", labels: ["Service"] },
      ],
      edges: [
        { type: "ROUTES_TO", confidence: 0.98, min_confidence: 0.98, max_confidence: 0.98, via: ["gateway_config"], weight: 1, path_prefix: "/api/customer", evidence: ["src/main/resources/application.yml:34"] },
        { type: "CALLS_SERVICE", confidence: 0.85, min_confidence: 0.85, max_confidence: 0.85, via: ["http"], weight: 2, path_prefix: null, evidence: ["src/main/java/VisitsClient.java:44"] },
      ],
      min_confidence: 0.85,
      crossings: [],
    },
    {
      nodes: [
        { id: "global:Service:api-gateway", name: "api-gateway", labels: ["Service", "Gateway"] },
        { id: "global:Service:visits-service", name: "visits-service", labels: ["Service"] },
      ],
      edges: [
        { type: "CALLS_SERVICE", confidence: 0.72, min_confidence: 0.72, max_confidence: 0.72, via: ["http"], weight: 1, path_prefix: null, evidence: ["src/api/apiClient.ts:88"] },
      ],
      min_confidence: 0.72,
      crossings: [],
    },
  ] as any,
  warnings: [],
};

/**
 * Repo graph fixture, generated to the composition the live `overview` view
 * actually returns for spring-petclinic-microservices, measured against Neo4j:
 *
 *   187 File · 48 Dependency · 44 Class · 16 ApiEndpoint · 4 Folder · 1 Repo
 *
 * That is 300 nodes wired by CONTAINS/DECLARES — a containment forest, which
 * is 57% of all edges in the real estate. Generated rather than hardcoded so
 * the file stays readable while still reproducing the real size and shape:
 * a 300-node tree is what the repo tab has to lay out, and a 9-node toy would
 * hide every problem that causes.
 */
function buildRepoGraph(): { nodes: GraphNode[]; links: GraphLink[]; stats: GraphStats } {
  const nodes: GraphNode[] = [];
  const links: GraphLink[] = [];
  const repoId = "spring-petclinic_spring-petclinic-microservices";

  const node = (
    id: string, type: string, name: string, group: string, size = 4,
    path?: string, language?: string, metadata: Record<string, unknown> = {},
  ): GraphNode => {
    const n: GraphNode = { id, type, label: name, name, size, group, metadata, path, language };
    nodes.push(n);
    return n;
  };
  const link = (source: string, target: string, type: string) => {
    links.push({ id: `${source}->${target}`, source, target, type, label: type, value: 1, confidence: null });
  };

  node(`${repoId}:repo`, "Repo", "spring-petclinic-microservices", "root", 12);

  const services = ["customers-service", "vets-service", "visits-service", "api-gateway"];
  services.forEach((svc) => {
    const folder = `${repoId}:folder:${svc}`;
    node(folder, "Folder", svc, svc, 8);
    link(`${repoId}:repo`, folder, "CONTAINS");
  });

  // Files spread across the four service folders, matching the 187 measured.
  for (let i = 0; i < 187; i++) {
    const svc = services[i % services.length];
    const id = `${repoId}:file:${i}`;
    node(id, "File", `${svc.split("-")[0]}Component${i}.java`, svc, 4,
      `spring-petclinic-${svc}/src/main/java/org/springframework/samples/petclinic/${svc.split("-")[0]}/Component${i}.java`,
      "java", { loc: 40 + ((i * 17) % 260), package: `org.springframework.samples.petclinic.${svc.split("-")[0]}` });
    link(`${repoId}:folder:${svc}`, id, "CONTAINS");
  }

  for (let i = 0; i < 44; i++) {
    const fileIdx = i * 4;
    const id = `${repoId}:class:${i}`;
    node(id, "Class", `PetClinicService${i}`, services[i % services.length], 5,
      `spring-petclinic-${services[i % services.length]}/src/main/java/.../PetClinicService${i}.java`,
      "java", { methods: 3 + (i % 9), visibility: "public" });
    link(`${repoId}:file:${fileIdx}`, id, "DECLARES");
  }

  for (let i = 0; i < 16; i++) {
    const id = `${repoId}:api:${i}`;
    node(id, "ApiEndpoint", `GET /api/${services[i % services.length]}/${i}`, services[i % services.length], 6,
      undefined, undefined,
      { http_method: "GET", route: `/api/${services[i % services.length]}/${i}`,
        handler: `PetClinicService${i}.handle`, framework: "spring-web",
        declared_at: `src/main/java/.../PetClinicService${i}.java:${30 + i}` });
    link(`${repoId}:class:${i}`, id, "EXPOSES_API");
  }

  const deps = ["spring-boot-starter-web", "spring-cloud-starter-netflix-eureka-client",
    "spring-boot-starter-data-jpa", "micrometer-registry-prometheus", "hsqldb",
    "spring-cloud-starter-config", "jackson-databind", "lombok"];
  for (let i = 0; i < 48; i++) {
    const id = `${repoId}:dep:${i}`;
    node(id, "Dependency", `${deps[i % deps.length]}${i >= deps.length ? `-${Math.floor(i / deps.length)}` : ""}`, "deps", 5,
      undefined, undefined,
      { ecosystem: "maven", purl: `pkg:maven/org.springframework.boot/${deps[i % deps.length]}`,
        scope: i % 7 === 0 ? "test" : "compile", declared_in: "pom.xml" });
    link(`${repoId}:repo`, id, "DEPENDS_ON");
  }

  const nodeTypes: Record<string, number> = {};
  nodes.forEach((n) => { nodeTypes[n.type] = (nodeTypes[n.type] ?? 0) + 1; });
  const edgeTypes: Record<string, number> = {};
  links.forEach((l) => { edgeTypes[l.type] = (edgeTypes[l.type] ?? 0) + 1; });

  return {
    nodes,
    links,
    stats: {
      total_nodes: nodes.length, total_edges: links.length,
      node_types: nodeTypes, edge_types: edgeTypes,
      files: nodeTypes.File ?? 0, apis: nodeTypes.ApiEndpoint ?? 0,
      dependencies: nodeTypes.Dependency ?? 0, external_systems: 0,
    },
  };
}

export const PREVIEW_REPO_GRAPH = buildRepoGraph();
