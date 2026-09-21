// Mock Career Paths Data
const mockPaths = {
  "frontend_fullstack": {
    title: "Frontend to Full Stack Engineer",
    stages: [
      { id: "stage1", title: "1. Advanced Frontend" },
      { id: "stage2", title: "2. Backend Core" },
      { id: "stage3", title: "3. Systems & Databases" },
      { id: "stage4", title: "4. Deployment & DevOps" }
    ],
    nodes: [
      {
        id: "adv_js",
        stage: "stage1",
        title: "Advanced JavaScript",
        desc: "Deep dive into JS engines, scoping, closures, async models, event loop, and performance profiling.",
        dependencies: [],
        defaultState: "mastered",
        curriculum: [
          "Understanding V8 engine & memory management",
          "Advanced closures, lexical scope, and prototypes",
          "Asynchronous flow: Promises, Async/Await, Web Workers",
          "Memory leaks, garbage collection, and profiling"
        ],
        resources: [
          { name: "You Don't Know JS Yet", platform: "GitHub Book", url: "https://github.com/getify/You-Dont-Know-JS" },
          { name: "JavaScript.info (Advanced)", platform: "Free Course", url: "https://javascript.info/" }
        ]
      },
      {
        id: "nextjs",
        stage: "stage1",
        title: "Next.js & Server Rendering",
        desc: "Mastering React Server Components (RSC), server actions, dynamic routing, and hybrid rendering strategies.",
        dependencies: ["adv_js"],
        defaultState: "mastered",
        curriculum: [
          "Client vs Server Components architecture",
          "Streaming HTML & Selective Hydration",
          "Server Actions & Form management",
          "Incremental Static Regeneration (ISR) and SSG"
        ],
        resources: [
          { name: "Next.js Learn Course", platform: "Official Docs", url: "https://nextjs.org/learn" },
          { name: "RSC deep dive", platform: "YouTube (Josh W Comeau)", url: "https://www.youtube.com/" }
        ]
      },
      {
        id: "node_api",
        stage: "stage2",
        title: "Node.js & API Design",
        desc: "Creating highly scalable RESTful services, middleware pipelines, error handling, and authentication protocols.",
        dependencies: ["nextjs"],
        defaultState: "inprogress",
        curriculum: [
          "Event-driven architecture and cluster module",
          "Express/Fastify middleware pipelines",
          "JWT & OAuth2 authentication patterns",
          "Global error handling & structured logging"
        ],
        resources: [
          { name: "Node.js Developer Guide", platform: "MDN", url: "https://developer.mozilla.org/en-US/docs/Learn/Server-side/Express_Nodejs" },
          { name: "Build a REST API with Node", platform: "freeCodeCamp", url: "https://www.freecodecamp.org/news/build-a-rest-api-with-node-express/" }
        ]
      },
      {
        id: "db_sql",
        stage: "stage3",
        title: "Database Foundations",
        desc: "Relational modeling, SQL constraints, indexing strategies, query analysis, and ACID transactions.",
        dependencies: ["node_api"],
        defaultState: "inprogress",
        curriculum: [
          "Normal forms (1NF, 2NF, 3NF) & Schema design",
          "Writing optimized JOINs, subqueries, and views",
          "Indexes: B-Trees, Hash indexes, and execution plans",
          "ACID compliance & Transaction isolation levels"
        ],
        resources: [
          { name: "SQL Tutorial", platform: "W3Schools", url: "https://www.w3schools.com/sql/" },
          { name: "Database Design Course", platform: "freeCodeCamp", url: "https://www.youtube.com/watch?v=ztHopE5Wubs" }
        ]
      },
      {
        id: "orms",
        stage: "stage3",
        title: "ORMs & Integration",
        desc: "Seamless integration using Prisma or Sequelize, writing migrations, relations mapping, and query optimization.",
        dependencies: ["db_sql"],
        defaultState: "locked",
        curriculum: [
          "Prisma Client configuration & schema models",
          "Automating database migrations",
          "Mitigating the N+1 query problem",
          "Handling database connection pooling"
        ],
        resources: [
          { name: "Prisma Quick Start", platform: "Prisma Docs", url: "https://www.prisma.io/docs/getting-started" }
        ]
      },
      {
        id: "cloud_devops",
        stage: "stage4",
        title: "CI/CD & Cloud Deployment",
        desc: "Deploying full-stack apps to AWS/Vercel, managing environment vaults, and orchestrating GitHub Actions pipelines.",
        dependencies: ["orms"],
        defaultState: "locked",
        curriculum: [
          "Containerizing with Dockerfiles",
          "GitHub Actions CI/CD workflow pipelines",
          "AWS ECS/App Runner basics",
          "Monitoring logs with Datadog or CloudWatch"
        ],
        resources: [
          { name: "GitHub Actions Guide", platform: "GitHub Docs", url: "https://docs.github.com/en/actions" },
          { name: "Docker for Beginners", platform: "YouTube", url: "https://www.youtube.com/watch?v=fqMOX6JJhGo" }
        ]
      }
    ],
    connections: [
      { from: "adv_js", to: "nextjs" },
      { from: "nextjs", to: "node_api" },
      { from: "node_api", to: "db_sql" },
      { from: "db_sql", to: "orms" },
      { from: "orms", to: "cloud_devops" }
    ]
  },
  "backend_cloud": {
    title: "Backend Developer to Cloud Architect",
    stages: [
      { id: "stage1", title: "1. Advanced Backend" },
      { id: "stage2", title: "2. Cloud Services" },
      { id: "stage3", title: "3. Infrastructure & IaC" },
      { id: "stage4", title: "4. Cloud Architectures" }
    ],
    nodes: [
      {
        id: "sys_design",
        stage: "stage1",
        title: "System Design Basics",
        desc: "Load balancers, caching, microservices, consistency models, CAP theorem, and event-driven backends.",
        dependencies: [],
        defaultState: "mastered",
        curriculum: [
          "Load balancing (Algorithms, Layer 4 vs Layer 7)",
          "Caching strategies (Write-through, eviction policies)",
          "Event-driven architecture: Kafka, RabbitMQ basics",
          "Understanding CAP Theorem and trade-offs"
        ],
        resources: [
          { name: "System Design Primer", platform: "GitHub", url: "https://github.com/donnemartin/system-design-primer" }
        ]
      },
      {
        id: "aws_core",
        stage: "stage2",
        title: "AWS Core Services",
        desc: "Mastering EC2 computing, S3 object storage, VPC network topologies, and IAM authorization systems.",
        dependencies: ["sys_design"],
        defaultState: "mastered",
        curriculum: [
          "VPC setup: Subnets, Route Tables, NAT Gateways",
          "IAM: Users, Groups, Roles, Policies",
          "Compute: EC2 instances, Autoscaling groups",
          "S3 lifecycle policies and security buckets"
        ],
        resources: [
          { name: "AWS Cloud Practitioner Essentials", platform: "AWS Training", url: "https://aws.amazon.com/training/digital/aws-cloud-practitioner-essentials/" }
        ]
      },
      {
        id: "docker_containers",
        stage: "stage2",
        title: "Containers & Docker",
        desc: "Containerizing backend workloads, writing secure Dockerfiles, networking containers, and multi-stage builds.",
        dependencies: ["aws_core"],
        defaultState: "inprogress",
        curriculum: [
          "Docker daemon and engine architecture",
          "Writing optimized, multi-stage Dockerfiles",
          "Docker Compose for multi-container local testing",
          "Container networking and storage volumes"
        ],
        resources: [
          { name: "Docker Curriculum", platform: "Docker Labs", url: "https://docker-curriculum.com/" }
        ]
      },
      {
        id: "k8s_orchestrate",
        stage: "stage3",
        title: "Kubernetes Orchestration",
        desc: "Orchestrating container groups using Pods, Deployments, Services, Ingress controllers, and ConfigMaps.",
        dependencies: ["docker_containers"],
        defaultState: "locked",
        curriculum: [
          "Kubernetes architecture: Control plane vs Nodes",
          "Writing YAML manifests for Pods and Deployments",
          "Kubernetes Services: ClusterIP, NodePort, LoadBalancer",
          "Managing configs with ConfigMaps & Secrets"
        ],
        resources: [
          { name: "Kubernetes Basics", platform: "Kubernetes.io", url: "https://kubernetes.io/docs/tutorials/kubernetes-basics/" }
        ]
      },
      {
        id: "terraform_iac",
        stage: "stage3",
        title: "Infrastructure as Code",
        desc: "Declaring infrastructure configurations using HashiCorp Terraform syntax, state locking, and modular assets.",
        dependencies: ["k8s_orchestrate"],
        defaultState: "locked",
        curriculum: [
          "Terraform providers, resources, variables",
          "Managing state file locks with S3 & DynamoDB",
          "Structuring reusable Terraform Modules",
          "Executing plan, apply, and destroy steps safely"
        ],
        resources: [
          { name: "HashiCorp Learn: Terraform", platform: "HashiCorp", url: "https://developer.hashicorp.com/terraform/tutorials" }
        ]
      },
      {
        id: "serverless_arch",
        stage: "stage4",
        title: "Serverless Architectures",
        desc: "Designing event-driven backends using AWS Lambda, API Gateway, DynamoDB, SQS, and CloudWatch metrics.",
        dependencies: ["terraform_iac"],
        defaultState: "locked",
        curriculum: [
          "AWS Lambda compute runtime limits",
          "Configuring API Gateway integrations",
          "Event sources: DynamoDB Streams, S3 events, SQS",
          "Monitoring performance and Cold Start optimization"
        ],
        resources: [
          { name: "Serverless Framework Course", platform: "Serverless.com", url: "https://www.serverless.com/framework/docs/providers/aws/guide/intro" }
        ]
      }
    ],
    connections: [
      { from: "sys_design", to: "aws_core" },
      { from: "aws_core", to: "docker_containers" },
      { from: "docker_containers", to: "k8s_orchestrate" },
      { from: "k8s_orchestrate", to: "terraform_iac" },
      { from: "terraform_iac", to: "serverless_arch" }
    ]
  },
  "qa_devops": {
    title: "QA Engineer to DevOps Engineer",
    stages: [
      { id: "stage1", title: "1. Automation & Scripting" },
      { id: "stage2", title: "2. Pipelines & Platforms" },
      { id: "stage3", title: "3. Provisioning" },
      { id: "stage4", title: "4. Monitoring" }
    ],
    nodes: [
      {
        id: "linux_shell",
        stage: "stage1",
        title: "Linux & Shell Scripting",
        desc: "Mastering CLI commands, process limits, permissions, bash automating utilities, and cron triggers.",
        dependencies: [],
        defaultState: "mastered",
        curriculum: [
          "Navigating Linux filesystems & Unix permissions",
          "Bash script constructs: loops, args, exit codes",
          "Text processors: awk, sed, grep, cut",
          "Cron job automation schedules"
        ],
        resources: [
          { name: "Linux Journey", platform: "Free Interactive", url: "https://linuxjourney.com/" }
        ]
      },
      {
        id: "github_actions",
        stage: "stage2",
        title: "CI/CD & GitHub Actions",
        desc: "Building automated workflows, compiling artifacts, secure credential storage, and cloud runners.",
        dependencies: ["linux_shell"],
        defaultState: "mastered",
        curriculum: [
          "GitHub Actions syntax: workflows, jobs, steps",
          "Handling action secrets & environments",
          "Caching node_modules and dependency artifacts",
          "Creating test coverage reports automatically"
        ],
        resources: [
          { name: "Learn GitHub Actions", platform: "Official Docs", url: "https://docs.github.com/en/actions/learn-github-actions" }
        ]
      },
      {
        id: "docker_basics",
        stage: "stage2",
        title: "Docker Containerization",
        desc: "Packaging local web services into images, handling environments, routing ports, and composing services.",
        dependencies: ["github_actions"],
        defaultState: "inprogress",
        curriculum: [
          "Writing single-stage Dockerfiles",
          "Docker environment variables and port exposes",
          "Docker volumes for database persistent caching",
          "Docker Compose files for automation tests"
        ],
        resources: [
          { name: "Play with Docker", platform: "Interactive Sandbox", url: "https://labs.play-with-docker.com/" }
        ]
      },
      {
        id: "tf_provision",
        stage: "stage3",
        title: "Infrastructure Terraform",
        desc: "Deploying basic VM nodes, setting firewalls, network routers, and securing credential state maps.",
        dependencies: ["docker_basics"],
        defaultState: "locked",
        curriculum: [
          "Declaring basic AWS resources (EC2, VPC)",
          "Input variables and configuration outputs",
          "Managing local vs remote terraform state files",
          "Applying config updates without service downtime"
        ],
        resources: [
          { name: "Terraform Get Started Guide", platform: "HashiCorp", url: "https://developer.hashicorp.com/terraform/tutorials/aws-get-started" }
        ]
      },
      {
        id: "ansible_config",
        stage: "stage3",
        title: "Ansible Configuration",
        desc: "Provisioning remote servers, formatting YAML playbooks, creating host inventories, and server hardening.",
        dependencies: ["tf_provision"],
        defaultState: "locked",
        curriculum: [
          "Writing Ansible inventory lists and host targets",
          "Creating playbooks for installing packages (nginx, systemd)",
          "Templating dynamic configs with Jinja2 in Ansible",
          "Securing SSH access and setting up firewalls"
        ],
        resources: [
          { name: "Ansible Community Tutorials", platform: "Ansible Docs", url: "https://docs.ansible.com/" }
        ]
      },
      {
        id: "metrics_observability",
        stage: "stage4",
        title: "Monitoring & Prometheus",
        desc: "Gathering system metrics, configuring Prometheus scraping, writing Grafana dashboard charts, and setup alerts.",
        dependencies: ["ansible_config"],
        defaultState: "locked",
        curriculum: [
          "Prometheus node_exporter metric scraping setup",
          "Configuring Prometheus YAML scrape schedules",
          "Building visual metrics charts in Grafana",
          "Setting up Slack/Email system crash alerts"
        ],
        resources: [
          { name: "Prometheus Monitoring Guide", platform: "Prometheus.io", url: "https://prometheus.io/docs/introduction/overview/" }
        ]
      }
    ],
    connections: [
      { from: "linux_shell", to: "github_actions" },
      { from: "github_actions", to: "docker_basics" },
      { from: "docker_basics", to: "tf_provision" },
      { from: "tf_provision", to: "ansible_config" },
      { from: "ansible_config", to: "metrics_observability" }
    ]
  },
  "student_backend": {
    title: "Student to Backend Developer",
    stages: [
      { id: "stage1", title: "1. Coding Basics" },
      { id: "stage2", title: "2. Databases" },
      { id: "stage3", title: "3. Web Backend" },
      { id: "stage4", title: "4. REST APIs & Deploy" }
    ],
    nodes: [
      {
        id: "python_oop",
        stage: "stage1",
        title: "Python & OOP Concepts",
        desc: "Variables, structures (lists/dicts), functions, classes, inheritance, decorators, and basic clean code practices.",
        dependencies: [],
        defaultState: "mastered",
        curriculum: [
          "Variables, Loops, Conditions, Lists, Dicts",
          "Functions, Return values, Parameter handling",
          "Classes, Objects, Methods, and Inheritance",
          "Basic file reads/writes and Exception handling"
        ],
        resources: [
          { name: "Python for Beginners", platform: "freeCodeCamp", url: "https://www.youtube.com/watch?v=rfscVS0vtbw" },
          { name: "Automate the Boring Stuff", platform: "Free eBook", url: "https://automatetheboringstuff.com/" }
        ]
      },
      {
        id: "git_basics",
        stage: "stage1",
        title: "Git & Collaborative Code",
        desc: "Initializing repositories, staging edits, writing commits, branching, pushing to GitHub, and pull requests.",
        dependencies: ["python_oop"],
        defaultState: "mastered",
        curriculum: [
          "Git configuration: init, clone, add, commit",
          "Branching workflows (main, feature branches)",
          "Pushing/pulling remote changes to GitHub",
          "Resolving simple merge conflicts"
        ],
        resources: [
          { name: "Git Immersion", platform: "Walkthrough", url: "https://gitimmersion.com/" },
          { name: "GitHub Skills", platform: "GitHub Lab", url: "https://skills.github.com/" }
        ]
      },
      {
        id: "mysql_basics",
        stage: "stage2",
        title: "MySQL Database Basics",
        desc: "Creating database tables, mapping keys, query joins, writing insert statements, and schema filtering.",
        dependencies: ["git_basics"],
        defaultState: "inprogress",
        curriculum: [
          "Creating tables with Primary & Foreign keys",
          "SELECT statements with WHERE, ORDER BY, LIMIT filters",
          "Query joins: INNER JOIN, LEFT JOIN concepts",
          "Writing basic INSERT, UPDATE, DELETE queries"
        ],
        resources: [
          { name: "MySQL Tutorial", platform: "W3Schools", url: "https://www.w3schools.com/mysql/" }
        ]
      },
      {
        id: "flask_routes",
        stage: "stage3",
        title: "Flask Web Server Basics",
        desc: "Setting up a Python Flask application, listening on routes, returning HTML templates, and parsing requests.",
        dependencies: ["mysql_basics"],
        defaultState: "inprogress",
        curriculum: [
          "Setting up virtual environments (venv)",
          "Creating route endpoints and mapping parameters",
          "Jinja2 HTML rendering with database context objects",
          "Handling POST and GET requests in controller functions"
        ],
        resources: [
          { name: "Flask Mega-Tutorial", platform: "Miguel Grinberg Blog", url: "https://blog.miguelgrinberg.com/post/the-flask-mega-tutorial-part-i-hello-world" }
        ]
      },
      {
        id: "rest_apis",
        stage: "stage4",
        title: "REST API Principles",
        desc: "Designing endpoint paths, returning JSON schemas, status responses, and authentication middlewares.",
        dependencies: ["flask_routes"],
        defaultState: "locked",
        curriculum: [
          "HTTP verbs: GET, POST, PUT, DELETE rules",
          "Setting exact HTTP Status Codes (200, 201, 400, 404, 500)",
          "Parsing JSON request payloads inside Flask",
          "Basic API validation guards"
        ],
        resources: [
          { name: "REST API tutorial", platform: "RESTfulAPI.net", url: "https://restfulapi.net/" }
        ]
      },
      {
        id: "render_deploy",
        stage: "stage4",
        title: "Render Cloud Deployment",
        desc: "Hosting a Python web app in the cloud, setting environmental credentials, and database migrations.",
        dependencies: ["rest_apis"],
        defaultState: "locked",
        curriculum: [
          "Creating WSGI configurations (gunicorn setup)",
          "Defining dependencies inside requirements.txt",
          "Connecting remote PostgreSQL/MySQL databases",
          "Configuring variables on Render dashboard"
        ],
        resources: [
          { name: "Deploying Flask to Render", platform: "Render Docs", url: "https://render.com/docs/deploy-flask" }
        ]
      }
    ],
    connections: [
      { from: "python_oop", to: "git_basics" },
      { from: "git_basics", to: "mysql_basics" },
      { from: "mysql_basics", to: "flask_routes" },
      { from: "flask_routes", to: "rest_apis" },
      { from: "rest_apis", to: "render_deploy" }
    ]
  }
};

// State Variables
let currentPathId = "frontend_fullstack";
let selectedNodeId = null;
let skillStates = {};

// Any current/target role text is allowed now — these presets just give
// instant (no-API-call) results for the same four combos that used to be
// the only options, and seed the "Popular" quick-pick chips below the
// inputs. Anything else typed goes straight to Gemini via
// fetchGeneratedPath, since the backend already accepts arbitrary role text.
const QUICK_PICKS = [
  { current: "Frontend Developer", target: "Full Stack Engineer", pathId: "frontend_fullstack" },
  { current: "Backend Developer", target: "Cloud Architect", pathId: "backend_cloud" },
  { current: "QA Engineer", target: "DevOps Engineer", pathId: "qa_devops" },
  { current: "Student / Explorer", target: "Backend Developer", pathId: "student_backend" },
  { current: "Data Analyst", target: "Data Scientist" },
  { current: "UI/UX Designer", target: "Product Manager" },
];

// Lookup so typing an exact preset pair still resolves to the pre-cached
// mockPaths entry instead of round-tripping to the AI.
const PRESET_ALIASES = {};
QUICK_PICKS.forEach(p => {
  if (p.pathId) {
    PRESET_ALIASES[`${p.current.toLowerCase()}|${p.target.toLowerCase()}`] = p.pathId;
  }
});

// Initialize application
document.addEventListener("DOMContentLoaded", () => {
  const currentInput = document.getElementById("currentRoleInput");
  const targetInput = document.getElementById("targetRoleInput");
  const btnGenerate = document.getElementById("btnGenerate");

  renderQuickPicks();

  const runGenerate = () => {
    const currentVal = currentInput.value.trim();
    const targetVal = targetInput.value.trim();

    if (!currentVal || !targetVal) {
      showSelectorError("Enter both a current role and a target role to generate a path.");
      return;
    }
    if (currentVal.toLowerCase() === targetVal.toLowerCase()) {
      showSelectorError("Current role and target role should be different.");
      return;
    }
    clearSelectorError();
    loadPath(getPathKey(currentVal, targetVal), currentVal, targetVal);
  };

  btnGenerate.addEventListener("click", runGenerate);
  [currentInput, targetInput].forEach(inp => {
    inp.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        runGenerate();
      }
    });
  });

  // Prefill from the user's saved profile role if present, otherwise fall
  // back to the first preset. Either way, load instantly from mockPaths
  // (no API call) for the first paint.
  if (!currentInput.value.trim()) currentInput.value = "Frontend Developer";
  if (!targetInput.value.trim()) targetInput.value = "Full Stack Engineer";

  const initialKey = getPathKey(currentInput.value.trim(), targetInput.value.trim());
  loadPath(initialKey, currentInput.value.trim(), targetInput.value.trim());

  // Redraw connections on window resize
  window.addEventListener("resize", () => {
    requestAnimationFrame(drawLines);
  });
});

function renderQuickPicks() {
  const container = document.getElementById("quick-picks");
  if (!container) return;
  QUICK_PICKS.forEach(pick => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "quick-pick-chip";
    chip.textContent = `${pick.current} → ${pick.target}`;
    chip.addEventListener("click", () => {
      document.getElementById("currentRoleInput").value = pick.current;
      document.getElementById("targetRoleInput").value = pick.target;
      clearSelectorError();
      loadPath(getPathKey(pick.current, pick.target), pick.current, pick.target);
    });
    container.appendChild(chip);
  });
}

function showSelectorError(message) {
  const el = document.getElementById("selector-error");
  if (!el) return;
  el.textContent = message;
  el.style.display = "block";
}

function clearSelectorError() {
  const el = document.getElementById("selector-error");
  if (!el) return;
  el.style.display = "none";
}

function slugify(text) {
  return (
    text
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "") || "role"
  );
}

function getPathKey(curr, target) {
  const aliasKey = `${curr.trim().toLowerCase()}|${target.trim().toLowerCase()}`;
  if (PRESET_ALIASES[aliasKey]) return PRESET_ALIASES[aliasKey];
  return `${slugify(curr)}__${slugify(target)}`;
}

// Load a specific path and merge states with localStorage. If we don't
// have this current/target combo cached yet, ask the backend (Gemini) to
// generate it, then cache the result in `mockPaths` under the same key so
// everything downstream (renderTree, drawLines, selectNode...) works
// unchanged.
async function loadPath(pathId, currentVal, targetVal) {
  const btnGenerate = document.getElementById("btnGenerate");

  if (!mockPaths[pathId]) {
    showTreeLoading();
    if (btnGenerate) btnGenerate.disabled = true;

    try {
      const generated = await fetchGeneratedPath(currentVal, targetVal);
      mockPaths[pathId] = generated;
    } catch (err) {
      console.error("Pathfinder generation failed:", err);
      showTreeError(err.message || "Couldn't generate this path. Try again.");
      if (btnGenerate) btnGenerate.disabled = false;
      return;
    }

    if (btnGenerate) btnGenerate.disabled = false;
  }

  currentPathId = pathId;
  selectedNodeId = null;

  // Retrieve saved states or load default states
  const savedStatesRaw = localStorage.getItem(`careeros_pathfinder_states_${pathId}`);
  if (savedStatesRaw) {
    try {
      skillStates = JSON.parse(savedStatesRaw);
    } catch (e) {
      console.error("Error loading localStorage states:", e);
      initializeDefaultStates(pathId);
    }
  } else {
    initializeDefaultStates(pathId);
  }

  // Update dynamic titles
  document.getElementById("pathfinder-title-text").textContent = mockPaths[pathId].title;

  renderTree();
  showEmptyDetailPanel();
}

// Calls the Flask backend, which asks Gemini for a skill tree matching
// the same shape as the hardcoded mockPaths entries above, and attaches
// one real YouTube video per node (see youtube_helper.py server-side).
async function fetchGeneratedPath(currentVal, targetVal) {
  const res = await fetch("/api/generate-pathfinder", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      current_role: currentVal,
      target_role: targetVal,
    }),
  });

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    throw new Error(data.error || "Something went wrong generating your pathfinder.");
  }

  return data.path;
}

function showTreeLoading() {
  const columnsContainer = document.getElementById("tree-columns");
  if (!columnsContainer) return;
  columnsContainer.innerHTML = `
    <div style="width:100%; text-align:center; padding:60px 0; color:var(--text-low);">
      <div style="font-size:0.9rem;">Generating your skill tree with AI…</div>
    </div>
  `;
  const svg = document.getElementById("connections-svg");
  if (svg) svg.innerHTML = "";
}

function showTreeError(message) {
  const columnsContainer = document.getElementById("tree-columns");
  if (!columnsContainer) return;
  columnsContainer.innerHTML = `
    <div style="width:100%; text-align:center; padding:60px 0; color:var(--text-low);">
      <div style="font-size:0.9rem; margin-bottom:6px;">⚠️ ${escapeHtmlPf(message)}</div>
      <div style="font-size:0.8rem;">Try selecting the roles again.</div>
    </div>
  `;
  const svg = document.getElementById("connections-svg");
  if (svg) svg.innerHTML = "";
}

function escapeHtmlPf(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function initializeDefaultStates(pathId) {
  skillStates = {};
  mockPaths[pathId].nodes.forEach(node => {
    skillStates[node.id] = node.defaultState;
  });
  saveStates();
}

function saveStates() {
  localStorage.setItem(`careeros_pathfinder_states_${currentPathId}`, JSON.stringify(skillStates));
}

// Render nodes in stage columns
function renderTree() {
  const path = mockPaths[currentPathId];
  const columnsContainer = document.getElementById("tree-columns");
  columnsContainer.innerHTML = "";

  path.stages.forEach(stage => {
    const col = document.createElement("div");
    col.className = "stage-column";

    const header = document.createElement("div");
    header.className = "stage-header";
    header.textContent = stage.title;
    col.appendChild(header);

    // Get nodes in this stage
    const stageNodes = path.nodes.filter(n => n.stage === stage.id);
    stageNodes.forEach(node => {
      const nodeEl = document.createElement("div");
      const state = skillStates[node.id];
      nodeEl.className = `skill-node state-${state}`;
      if (node.id === selectedNodeId) {
        nodeEl.classList.add("selected");
      }
      nodeEl.setAttribute("data-id", node.id);

      // Status indicator dot
      const dot = document.createElement("div");
      dot.className = "node-status-dot";
      nodeEl.appendChild(dot);

      // Title
      const title = document.createElement("div");
      title.className = "node-title";
      title.textContent = node.title;
      nodeEl.appendChild(title);

      // Description
      const desc = document.createElement("div");
      desc.className = "node-desc";
      desc.textContent = node.desc;
      nodeEl.appendChild(desc);

      // State Badge
      const badge = document.createElement("span");
      badge.className = `node-badge ${state}`;
      if (state === "locked") {
        badge.innerHTML = "🔒 Locked";
      } else if (state === "inprogress") {
        badge.innerHTML = "⚡ In Progress";
      } else if (state === "mastered") {
        badge.innerHTML = "✓ Mastered";
      }
      nodeEl.appendChild(badge);

      // Click handler
      nodeEl.addEventListener("click", () => {
        if (state === "locked") return; // cannot view locked details
        selectNode(node.id);
      });

      col.appendChild(nodeEl);
    });

    columnsContainer.appendChild(col);
  });

  // Schedule lines draw after elements are in DOM
  setTimeout(() => {
    requestAnimationFrame(drawLines);
  }, 50);
}

// Draw Bezier connections between node cards
function drawLines() {
  const svg = document.getElementById("connections-svg");
  if (!svg) return;
  svg.innerHTML = "";

  const path = mockPaths[currentPathId];
  const container = document.getElementById("tree-container-box");
  if (!container) return;

  const containerRect = container.getBoundingClientRect();
  svg.setAttribute("width", containerRect.width);
  svg.setAttribute("height", containerRect.height);

  path.connections.forEach(conn => {
    const fromEl = document.querySelector(`[data-id="${conn.from}"]`);
    const toEl = document.querySelector(`[data-id="${conn.to}"]`);
    if (!fromEl || !toEl) return;

    const fromRect = fromEl.getBoundingClientRect();
    const toRect = toEl.getBoundingClientRect();

    // Check if layout is horizontal (columns flow side by side) or stacked vertical (mobile layout)
    const isMobile = window.innerWidth <= 950;

    let x1, y1, x2, y2;
    if (isMobile) {
      // Connect bottom edge of 'from' to top edge of 'to'
      x1 = fromRect.left + fromRect.width / 2 - containerRect.left;
      y1 = fromRect.bottom - containerRect.top;
      x2 = toRect.left + toRect.width / 2 - containerRect.left;
      y2 = toRect.top - containerRect.top;
    } else {
      // Connect right edge of 'from' to left edge of 'to'
      x1 = fromRect.right - containerRect.left;
      y1 = fromRect.top + fromRect.height / 2 - containerRect.top;
      x2 = toRect.left - containerRect.left;
      y2 = toRect.top + toRect.height / 2 - containerRect.top;
    }

    const pathEl = document.createElementNS("http://www.w3.org/2000/svg", "path");
    let dStr = "";

    if (isMobile) {
      // S-curve vertical
      const dy = Math.abs(y2 - y1) * 0.5;
      dStr = `M ${x1} ${y1} C ${x1} ${y1 + dy}, ${x2} ${y2 - dy}, ${x2} ${y2}`;
    } else {
      // S-curve horizontal
      const dx = Math.abs(x2 - x1) * 0.5;
      dStr = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
    }

    pathEl.setAttribute("d", dStr);

    // Style lines based on progress
    const fromState = skillStates[conn.from];
    const toState = skillStates[conn.to];
    if (fromState === "mastered" && toState !== "locked") {
      pathEl.setAttribute("class", "connection-line active");
    } else {
      pathEl.setAttribute("class", "connection-line");
    }

    svg.appendChild(pathEl);
  });
}

function showEmptyDetailPanel() {
  const panel = document.getElementById("detail-panel-box");
  panel.innerHTML = `
    <div class="detail-empty">
      <svg fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3Z"/></svg>
      <p style="font-size: 0.9rem;">Click on any unlocked skill card to view curriculum & study resources.</p>
    </div>
  `;
}

// Select a node and populate details pane
function selectNode(nodeId) {
  selectedNodeId = nodeId;

  // Highlight selected node card
  document.querySelectorAll(".skill-node").forEach(el => {
    el.classList.remove("selected");
  });
  const activeCard = document.querySelector(`[data-id="${nodeId}"]`);
  if (activeCard) {
    activeCard.classList.add("selected");
  }

  const node = mockPaths[currentPathId].nodes.find(n => n.id === nodeId);
  if (!node) return;

  const state = skillStates[nodeId];
  const panel = document.getElementById("detail-panel-box");

  // Generate curriculum list elements
  const curriculumHtml = node.curriculum.map(item => `<li>${item}</li>`).join("");

  // Generate resource links list
  const resourcesHtml = node.resources.map(res => `
    <a href="${res.url}" target="_blank" class="resource-item">
      <div class="resource-info">
        <span class="resource-name">${res.name}</span>
        <span class="resource-platform">${res.platform}</span>
      </div>
      <div class="resource-link">
        <svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25"/></svg>
      </div>
    </a>
  `).join("");

  // Generate state status switcher button
  let actionButtonHtml = "";
  if (state === "inprogress") {
    actionButtonHtml = `
      <button class="btn-status-toggle to-master" onclick="updateNodeState('${nodeId}', 'mastered')">
        Mark as Mastered
      </button>
    `;
  } else if (state === "mastered") {
    actionButtonHtml = `
      <button class="btn-status-toggle completed-btn" disabled>
        ✓ Completed & Mastered
      </button>
    `;
  }

  panel.innerHTML = `
    <div class="detail-header">
      <span style="font-size: 0.72rem; color: var(--text-low); text-transform: uppercase; font-weight: 700; letter-spacing: 0.05em;">SKILL NODE</span>
      <h2 class="detail-title">${node.title}</h2>
    </div>

    <div class="detail-section">
      <h4>Description</h4>
      <p class="detail-desc">${node.desc}</p>
    </div>

    <div class="detail-section">
      <h4>Core Curriculum</h4>
      <ul class="curriculum-list">
        ${curriculumHtml}
      </ul>
    </div>

    <div class="detail-section">
      <h4>Recommended Free Resources</h4>
      <div style="display: flex; flex-direction: column; gap: 8px;">
        ${resourcesHtml}
      </div>
    </div>

    <div class="status-action-box">
      <div class="status-label-row">
        <span>Current Status:</span>
        <span style="font-weight: 700; color: ${state === 'mastered' ? 'var(--purple-2)' : 'var(--blue)'};">
          ${state === 'mastered' ? 'Mastered' : 'In Progress'}
        </span>
      </div>
      ${actionButtonHtml}
    </div>
  `;
}

// Update state and propagate unlocks
window.updateNodeState = function(nodeId, newState) {
  skillStates[nodeId] = newState;

  // Propagate unlocks downstream
  propagateUnlocks();

  saveStates();
  renderTree();

  // Re-render the details panel with new state
  selectNode(nodeId);
};

// Check downstream dependencies and auto-unlock nodes
function propagateUnlocks() {
  const nodes = mockPaths[currentPathId].nodes;
  let updated = false;

  // We loop repeatedly until no more nodes change state to handle multi-level cascade unlocks
  do {
    updated = false;
    nodes.forEach(node => {
      // If a node is locked, check if all its dependencies are now mastered
      if (skillStates[node.id] === "locked") {
        const allDepsMastered = node.dependencies.every(depId => skillStates[depId] === "mastered");
        if (allDepsMastered) {
          skillStates[node.id] = "inprogress";
          updated = true;
        }
      }
    });
  } while (updated);
}
