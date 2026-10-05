# AWS CERTIFIED CLOUD PRACTITIONER (CLF-C02) - EXAM STUDY PLAN
**For:** Hope John Sunday | **Goal:** Pass within 3-4 weeks | **Format:** 65 questions, 90 minutes, 65% to pass (score ~700/1000)

---

## IMPORTANT BEHAVIORAL NOTE
Do NOT pay for exam prep courses. Free resources outperform paid ones for CLF-C02:
- **AWS Skill Builder** (free tier) - official AWS training
- **FreeCodeCamp / Andrew Brown CLF-C02 full course** (YouTube)
- **Tutorials Dojo practice exams** (only if you have budget - ~$15, gold standard)
- **ExamPro / Digital Cloud Training free video** (YouTube)

---

## WEEK 1 - CLOUD CONCEPTS & SECURITY (Days 1-7)

### Day 1-2: Cloud Concepts (15% of exam)
- [ ] IaaS vs PaaS vs SaaS (memorize 3 examples each)
- [ ] On-prem vs cloud: CapEx vs OpEx
- [ ] 6 AWS advantages: 1) Trade fixed expense for variable, 2) Economies of scale, 3) Stop guessing capacity, 4) Increase speed/agility, 5) Go global in minutes, 6) Avoid maintaining data centers
- [ ] 5 pillars of Well-Architected Framework: Operational Excellence, Security, Reliability, Performance Efficiency, Cost Optimization (mnemonic: "OSR PCC")
- [ ] High availability vs fault tolerance

### Day 3-5: Security & Compliance (30% of exam - MOST IMPORTANT)
- [ ] Shared Responsibility Model: AWS = security OF the cloud; Customer = security IN the cloud
- [ ] IAM: users, groups, roles, policies, root account (use MFA, never share)
- [ ] Protection methods: MFA, password policies, least privilege
- [ ] KMS (encryption keys), S3 server-side encryption, CloudTrail (audit trail)
- [ ] AWS Shield (DDoS) vs AWS WAF (web app firewall vs common web exploits)
- [ ] GuardDuty (threat detection), Inspector (vulnerability assessment), Macie (PII/data discovery - S3)
- [ ] Security Groups (instance-level virtual firewall, allow rules only) vs NACLs (subnet-level, allow/deny)
- [ ] Compliance programs: ISO 27001, SOC 1/2/3, HIPAA, PCI DSS - where to check = AWS Artifact
- [ ] Cognito (user sign-up/sign-in), AWS Config (resource configuration compliance)

### Day 6-7: Practice + Flashcards
- [ ] 30 free practice questions on Tutorials Dojo/FreeCodeCamp
- [ ] Make flashcards: examtopics (practice questions but beware wrong answers in comments)

---

## WEEK 2 - TECHNOLOGY: CORE AWS SERVICES (Days 8-14) (34% of exam - LARGEST)

### Compute:
- [ ] EC2: instances, AMIs, instance types (family letters: t=burstable, m=general, c=compute, r=memory, g=GPU), pricing models: On-Demand, Reserved, Spot, Savings Plans
- [ ] AWS Lambda: serverless, pay per invocation, no infrastructure
- [ ] ECS/EKS: containers; Fargate: serverless containers
- [ ] Elastic Beanstalk: PaaS for code deploy (no infra control)
- [ ] LightSail: simple VPS for beginners

### Storage:
- [ ] S3: object storage, bucket, regions, storage classes (Standard, Intelligent-Tiering, Glacier: archive, Reduced Redundancy), versioning, lifecycle policies
- [ ] EBS: block storage for EC2 (like a hard drive)
- [ ] EFS: file storage shared across instances (Linux)
- [ ] RDS: managed relational DB (Aurora = AWS's MySQL/Postgres engine)

### Databases:
- [ ] RDS vs DynamoDB (serverless NoSQL, key-value, millisecond latency)
- [ ] Aurora, Redshift (data warehouse / analytics), ElastiCache (in-memory cache)
- [ ] Choose per use case: relational? NoSQL? warehouse? analytics?

### Networking:
- [ ] VPC: virtual private cloud, subnets (public/private), route tables, Internet Gateway, NAT Gateway
- [ ] VPC peering, VPN, Direct Connect (dedicated physical line to AWS)
- [ ] Route 53: DNS service
- [ ] CloudFront: CDN edge locations, speed up content delivery
- [ ] Elastic Load Balancer (ELB): distributes traffic

### Day 13-14: Integration + Practice
- [ ] SQS (message queue), SNS (notifications/pub-sub), Step Functions (workflows), API Gateway
- [ ] EventBridge (event-driven)
- [ ] 40+ practice questions

---

## WEEK 3 - BILLING, PRICING & SUPPORT (Days 15-21) (20% of exam)

### Day 15-17:
- [ ] AWS Free Tier (free per month: 750hrs EC2, 5GB S3, 1M Lambda requests, etc.)
- [ ] AWS Pricing Calculator (estimate tool)
- [ ] AWS Budgets (set spend alerts), Cost Explorer (analyze spend)
- [ ] Consolidated billing (multiple accounts), AWS Organizations (account management/SCP)
- [ ] AWS Support plans: Basic (free), Developer, Business, Enterprise (all 4 = support levels)
- [ ] Trusted Advisor: checks best practices (cost, performance, security, fault tolerance, service limits; 7 checks free in basic)

### Day 18-20: Exam prep + weaknesses
- [ ] Review all flashcards and practice exams again
- [ ] Take 2 full-length practice exams (65 questions, timing yourself 90 min)
- [ ] Re-study all questions you got wrong

### Day 21: FINAL
- [ ] Take 1 last full practice exam; target 70%+ before booking
- [ ] Book the exam: pearsonvue.com / aws.training/certification exam

---

## TOP 20 MOST-TESTED FACTS (memorize these)

1. Shared Responsibility is foundation - memorize what is customer's vs AWS's
2. IAM = identity + permissions; policies = JSON documents; least privilege principle
3. Security Groups = allow-only instance firewall; NACLs = stateless allow/deny subnet firewall
4. S3 = object storage, unlimited, private by default, encryption via SSE (KMS/S3/AES-256)
5. Glacier = archive storage, cheapest, retrieval in minutes/hours
6. Lambda = serverless compute, pay per request, scales automatically
7. CloudFront = CDN (edge locations), NOT a load balancer
8. Route 53 = DNS; ELB = load balancing
9. Direct Connect = dedicated physical network to AWS (not over internet)
10. VPN = encrypted tunnel over the internet (vs Direct Connect = physical)
11. CloudTrail = API audit trail (who did what); CloudWatch = monitoring metrics/alarms/logs
12. KMS = managed encryption keys; Shield = DDoS protection; WAF = web filter
13. Organizations = central management of multiple AWS accounts + SCPs
14. Consolidated billing = aggregate usage across accounts for volume discounts
15. Trusted Advisor = recommends cost/performance/security improvements (7 free checks)
16. Pricing factors: region, instance type, data transfer, storage class, reserved/Savings Plan
17. Facings: On-Demand (flexible), Reserved (1-3yr commitment, save up to 72%), Spot (up to 90% off, interruptible), Savings Plans (compute commitment)
18. AWS support plans: Developer (1), Business (many alerts), Enterprise (everything + TAM + delegates)
19. Well-Architected: 5 pillars (naming above)
20. Amazon Cognito = auth for apps; AWS Config = resource configuration rules

---

## EXAM DAY TIPS
- 65 questions, 90 minutes = ~82 sec/question
- Flag and skip hard questions, return later
- Most questions have ONE clearly best answer - look for words like "most", "best", "SIMPLE", "cheapest", "FASTEST"
- Read the scenario twice - look for keywords: "audit" -> CloudTrail, "in-memory" -> ElastiCache, "serverless" -> Lambda, "DNS" -> Route 53, "CDN/global distribution" -> CloudFront, "archive" -> Glacier, "IDP/auth" -> Cognito, "account consolidation" -> Organizations
- You get a 10-min tutorial before exam; use it to warm up
- Pass mark: 700 out of 1000 (approx 65%)

## AFTER YOU PASS
- Add "AWS Certified Cloud Practitioner" to the TOP of ALL CV certifications (replace "In Progress")
- Regenerate your CV PDFs, retitle summaries ("AWS certified ..."), and re-send to Kolomolo/AWS-type roles