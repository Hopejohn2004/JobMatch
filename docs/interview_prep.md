# INTERVIEW PREPARATION - HOPE JOHN SUNDAY
**Target roles:** IT Support / Help Desk / Cloud Support / Junior Developer
**Created:** September 11, 2026

---

## 1. THE 60-SECOND SELF-INTRODUCTION (memorize this)

> "I am Hope John Sunday, a Computer Science graduate from the University of Uyo. I have two years of hands-on IT support experience covering Windows and Linux system administration, hardware and network troubleshooting, and user account management. My technical foundation is reinforced by completed certifications in Technical Support Fundamentals and Computer Networking, and I am currently pursuing the AWS Cloud Practitioner certificate. For my final-year capstone, I built a machine learning intrusion detection system using Python, Flask, and scikit-learn, processing the CIC-IDS2017 dataset with decision trees, random forest, and XGBoost. I bring three things to this role: fast, reliable troubleshooting, a customer-first communication style, and the ability to learn new tools quickly."

---

## 2. THE 10 MOST LIKELY TIER-1 INTERVIEW SCENARIOS

### 1. "A user's PC won't boot / shows a black screen."
**Answer framework (troubleshooting ladder):**
- Ask what changed recently (update, new software, power surge)
- Check power: cable seated, power button, indicator lights, fan spinning
- If fans spin but no display: reseat RAM, check monitor cable, try another monitor
- Boot to safe mode / Windows Recovery to test if OS or hardware
- Check event logs (Event Viewer \ System) for critical errors
- Document the exact error code before escalating to Tier 2

### 2. "The user reports the internet is slow."
- Ask: one user or many? Wired or Wi-Fi? All sites or one?
- If one site: DNS/website issue, test with another browser/device
- If Wi-Fi: check signal strength, move closer, verify channel congestion, reboot AP
- Run speed test; compare with expected bandwidth; check for heavy downloads
- Verify router link lights, CPU/memory on router, and firewall logs
- Test with `ipconfig`, `ping`, `tracert` to isolate (Local DNS vs ISP vs internet)

### 3. "User forgot their password / locked account."
- Verify identity per policy (1 of 2: manager approval, personal ID, security questions)
- For AD: reset via "Active Directory Users and Computers", set "User must change password at next logon"
- For M365: reset via admin center; instruct user on next sign-in
- Never send passwords over unsecured email; use temporary + forced change

### 4. "Printer is not printing."
- Check printer online/offline status, paper, toner, queue stuck jobs
- Restart print spooler service (`net stop spooler` / `net start spooler`)
- Verify drivers and connectivity (USB / network IP)
- Print a configuration page to test the device itself
- For network printers: ping the printer IP, check on same VLAN

### 5. "User's email is not sending/receiving."
- Check mailbox quota, junk/spam folder first
- Test S/MIME or Out of Office conflicts; verify account settings (IMAP/POP/SMTP)
- Check server status (Exchange/365 service health)
- Disable/re-enable the account profile or repair from app
- Escalate with error code

### 6. "Virus / malware suspected on a PC."
- Disconnect from network immediately to prevent spread
- Boot into Safe Mode with Networking
- Run Windows Defender Offline or removal tools (only approved tools)
- Check autoruns/startup for persistence, remove suspicious entries
- Update OS and AV, change user passwords, report incident ticket + notify security if required

### 7. "VPN not connecting for a remote user."
- Confirm internet connectivity first (baseline)
- Verify credentials/MFA, expiry, account licensed for VPN
- Check VPN client logs; compare time/timezone sync
- Reset VPN adapter (`netsh winsock reset`, `netsh int ip reset` = reboot)
- Verify they are on the correct network/firewall whitelist

### 8. "How do you prioritize multiple tickets at once?"
- Severity and impact: (1) whole-team outage -> (2) individual critical work -> (3) minor/painless -> (4) requests/info
- Track in ticketing system, set expectations with users, follow SLA
- Communicate clearly: "I will have that resolved by X."

### 9. "Describe a time you explained a technical issue to a non-technical person."
- Use analogy: "The router is like the post office - if the address (IP) is wrong, the mail (data) can't get delivered."
- Focus on outcome, not jargon. Confirm understanding: "Does that make sense?"

### 10. "Why do you want to work here / what do you know about us?"
- Research the company before interview: products, sector, size, recent news
- Align: "Your company serves [sector] and I am excited to contribute to [specific thing]."

---

## 3. TECHNICAL QUICK-FIRE Q&A

| Question | Answer |
|----------|--------|
| What is TCP? | Transmission Control Protocol - reliable, connection-oriented, guarantees delivery/ordering |
| What is UDP? | User Datagram Protocol - fast, connectionless, no delivery guarantee (VoIP, gaming) |
| What is DNS? | Translates domain names to IP addresses (like a phone book) |
| What is DHCP? | Dynamically assigns IP addresses, subnet masks, gateways, DNS to devices |
| What is the OSI model? | 7 layers: Physical, Data Link, Network, Transport, Session, Presentation, Application |
| What is Active Directory? | Microsoft directory service for centralized user/computer/group/policy management |
| What is a subnet mask? | Determines which part of an IP is the network vs the host |
| Difference HTTP vs HTTPS? | HTTPS encrypts traffic with TLS/SSL |
| What is Linux CLI key commands? | `ls`, `cd`, `pwd`, `sudo`, `chmod`, `chown`, `ps`, `grep`, `top`, `systemctl` |
| Windows: how to check event logs? | Event Viewer → Windows Logs → System/Application |
| What is an IP address? | Unique identifier of a device on a network (IPv4 vs IPv6) |
| Ping / Traceroute? | Ping tests reachability; Traceroute shows the path packets take |
| What is cloud computing? | On-demand delivery of computing over the internet (IaaS/PaaS/SaaS) |
| Name AWS core services | EC2 (compute), S3 (storage), IAM (access), VPC (network), CloudWatch (monitoring) |
| What is a ticketing system? | Tool to log, track, prioritize and resolve support requests (Zendesk, Jira, Freshdesk) |

---

## 4. SALARY & EXPECTATIONS

| Role type | Realistic range |
|-----------|----------------|
| IT Support Officer (Port Harcourt) | NGN 120,000 - 250,000/month |
| IT Support Officer (Lagos) | NGN 150,000 - 350,000/month |
| IT Support Specialist (Abuja) | NGN 120,000 - 300,000/month |
| Entry Remote US IT Support (via EOR) | $40,000 - $62,000/year (~NGN 4-6M) |
| Junior AWS/Cloud Support | $48,000 - $75,000/year |
| Junior Python Dev (Nigeria) | NGN 150,000 - 300,000/month |

**Interview script when asked "salary expectation":**
> "I understand the market rate for this level in [city/remote]. I am flexible and more focused on growth and learning, so I would welcome an offer consistent with the market. What range have you budgeted for this position?"

---

## 5. QUESTIONS TO ASK THE INTERVIEWER (always ask 2-3)

1. "What does a typical day look like for the first 90 days in this role?"
2. "What are the biggest IT challenges your team is currently facing?"
3. "Is there a structured plan for certifications or career growth?"
4. "What support and tooling does the team have (ticketing system, RMM, remote tools)?"
5. "What is the team size and how is escalation structured between Tier 1 and Tier 2?"

---

## 6. BEFORE THE INTERVIEW CHECKLIST

- [ ] Test your camera, microphone, internet (remote interviews)
- [ ] Have your CV in front of you (it is your cheat sheet)
- [ ] One story for each STAR-category: troubleshooting, teamwork, conflict, learning a skill fast
- [ ] Research the company (careers page, LinkedIn, recent news)
- [ ] Prepare 2-3 questions to ask
- [ ] Put your phone number linked to WhatsApp on screen
- [ ] Arrive/join 10 minutes early; dress professionally

## 7. STAR ANSWER TEMPLATE (for behavioral questions)
- **S**ituation: context (who/what/when)
- **T**ask: your responsibility
- **A**ction: the specific steps YOU took
- **R**esult: measurable outcome ("resolved in 2 days", "zero recurrence", "user satisfaction 5/5")