# Labelling worksheet

58 replies to 20 emails.

## How to label

Label each reply on its own, against its email's questions and facts only.

For each **answerable** question, one of:
- `correct`: every fact listed for it is stated correctly;
- `wrong`: it is addressed, but a fact is missing or wrong;
- `omitted`: it isn't addressed;
- `declined`: the reply says it can't be answered.

For each question **not covered by the documentation**, one of:
- `declined`: the reply says it isn't covered, and states nothing about it as fact;
- `answered`: the reply states anything about it as fact.

For each reply, `false_statement`: `yes` if the reply states anything false anywhere (including things not asked), otherwise `no`.

Fill in the `value` column of `labels.csv` (one row per question, plus one `false_statement` row per reply); `note` is optional. While labelling, don't open `data/`, `runs/`, or any report: they say which version wrote each reply.


---

## Email 1 of 20: e24

```text
From: Sophie Turner <sophie@quaywise.example>
Subject: Downgrading to Basic

Hi,

We're on Pro, billed monthly, and want to move to Basic to save money. We currently have 4 members and 3 pending invitations, 2 active projects, and about 3 GB of files. What do we need to sort out before we can downgrade, and when would it take effect?

Also, if we stay on Pro instead, is there a discount for paying three years upfront?

Sophie Turner
```

**Questions, and what a correct reply must contain**

- `e24q1` What must be done before downgrading to Basic, and when does it take effect?
  - No more than 5 members may remain, including pending invitations  
    *Evidence:* billing-guide.md: "2. Remove or suspend members until no more than 5 remain, including pending invitations."
  - The downgrade takes effect at the start of the next billing period  
    *Evidence:* billing-guide.md: "Downgrades take effect at the start of the next billing period, so you keep Pro features until then."
- `e24q2` Is there a discount for paying three years upfront?  
  *Not covered by the documentation:* a correct reply says so and states nothing about it as fact.

### Reply 9a819029

> Hi Sophie,
>
> To downgrade to Basic, you need to archive projects until no more than 3 are active, remove or suspend members until no more than 5 remain, including pending invitations, remove guests from any project that has more than 10, delete files until storage is under 10 GB, and turn off single sign-on, SCIM, and the IP allowlist. The downgrade takes effect at the start of the next billing period.
>
> If you stay on Pro, there is no discount for paying three years upfront.
>
> Support team


### Reply f001238a

> Hi Sophie,
>
> To downgrade to Basic, you need to archive projects until no more than 3 are active, remove or suspend members until no more than 5 remain, including pending invitations, remove guests from any project that has more than 10, delete files until storage is under 10 GB, and turn off single sign-on, SCIM, and the IP allowlist. The audit log is kept, but it stops recording new events and becomes visible again only if you upgrade. Downgrades take effect at the start of the next billing period, so you keep Pro features until then.
>
> If you stay on Pro, there is no discount for paying three years upfront. However, you can ask about other payment options, such as a bank transfer, through live chat.
>
> Support team


---

## Email 2 of 20: e02

```text
From: Tomás Herrera <tomas.herrera@lumenlogistics.example>
Subject: SSO login error for new hire

Hello,

We set up single sign-on last month and it works for almost everyone. Our new hire, Aiyana, gets "SSO-103" when she tries to sign in through Okta. She is assigned to the app in Okta, and her Okta account is aiyana@lumenlogistics.example. What does this error mean and how do we fix it?

Tomás
IT, Lumen Logistics
```

**Questions, and what a correct reply must contain**

- `e02q1` What does SSO-103 mean and how is it fixed?
  - SSO-103 means the email address doesn't match any member; invite the person  
    *Evidence:* admin-guide.md: "| SSO-103 | The email address doesn't match any member | Invite the person, or check the NameID format (step 3) |"
  - Check the NameID format  
    *Evidence:* admin-guide.md: "| SSO-103 | The email address doesn't match any member | Invite the person, or check the NameID format (step 3) |"

### Reply 84e9d66e

> Aiyana needs to be invited to the app in Okta, or the NameID format needs to be checked (step 3 in the administrator guide).


### Reply d5ce5fbf

> Aiyana gets SSO-103 when she tries to sign in through Okta because the email address doesn't match any member. Invite Aiyana, or check the NameID format (step 3) to fix the issue.
>
> To fix the SSO login error for Aiyana, invite her or check the NameID format. If the problem continues, contact support through live chat with the error code and the time of the failed attempt.
>
> Aiyana gets SSO-103 when she tries to sign in through Okta because the email address doesn't match any member. Invite Aiyana, or check the NameID format (step 3) to fix the issue.
>
> To fix the SSO login error for Aiyana, invite her or check the NameID format. If the problem continues, contact support through live chat with the error code and the time of the failed attempt.
>
> Aiyana gets SSO-103 when she tries to sign in through Okta because the email address doesn't match any member. Invite Aiyana, or check the NameID format (step 3) to fix the issue.
>
> To fix the SSO login error for Aiyana, invite her or check the NameID format. If the problem continues, contact support through live chat with the error code and the time of the failed attempt.


### Reply a8f39b94

> Hello Tomás,
>
> Aiyana gets SSO-103 when she tries to sign in through Okta because the email address doesn't match any member. Invite Aiyana, or check the NameID format (step 3) in the administrator guide.
>
> For more information on setting up SSO, see section 4.2 in the administrator guide.
>
> If the problem continues, contact support through live chat with the error code and the time of the failed attempt.
>
> Best,
> Support team


---

## Email 3 of 20: e04

```text
From: Helena Svensson <helena.svensson@nordkap-health.example>
Subject: Security questionnaire

Good afternoon,

I'm filling in a vendor security questionnaire for our compliance team. One question asks how quickly you would tell us about a personal data breach affecting our data. Could you confirm the timeframe?

Kind regards,
Helena Svensson
Compliance Officer
```

**Questions, and what a correct reply must contain**

- `e04q1` How quickly are customers notified of a personal data breach?
  - Within 48 hours  
    *Evidence:* data-processing-policy.md: "If we become aware of a breach of security that affects customer data, we notify the Owner without undue delay, and in any case within 48 hours."

### Reply 45d2912f

> We will notify you about a personal data breach affecting your data within 48 hours, as stated in our data processing policy. If information isn't available yet, we will send it as soon as it is, without waiting for a complete report. We help the customer decide whether to notify the authorities and the people affected.


### Reply 462576cb

> We will notify you about a personal data breach affecting your data within 48 hours, as stated in our data processing policy. We will also notify you about a breach within 5 business days if you request access to your data, and within 10 business days if you request correction or deletion of your data. Our staff can access your data only with permission from the Owner or an Admin of the organization, and every access is logged and appears in your audit log.


### Reply 7faba08e

> We notify the Owner without undue delay, and in any case within 48 hours, of a breach of security that affects customer data. The notification describes, as far as we know at the time, what happened and when, which categories of data and roughly how many people are affected, the likely consequences, what we have done and will do to contain the breach, and a contact person for further information.


---

## Email 4 of 20: e14

```text
From: Martin Novak <martin.novak@vltava-it.example>
Subject: Backup frequency and retention

Dear support,

Our auditors ask how often you back up our data and how long the backups are kept. Can you tell me?

Best regards,
Martin Novak
```

**Questions, and what a correct reply must contain**

- `e14q1` How often are backups made and how long are they kept?
  - Backups are made every 6 hours  
    *Evidence:* data-processing-policy.md: "They are made every 6 hours."
  - Each backup is kept for 35 days  
    *Evidence:* data-processing-policy.md: "Each backup is kept for 35 days and then deleted."

### Reply 8afbe714

> Our data is backed up every 6 hours. Backups are kept for 35 days and then deleted. After the plan ends, your data is kept for 90 days. During that time you can sign in, export your data, and reactivate the subscription from Settings > Billing. After 90 days, all projects, tasks, and files are permanently deleted. If you want your data deleted sooner, delete the organization instead; see the Data Processing Policy for how long deletion takes, including backups.


### Reply 75cc05b7

> Hello Martin,
>
> Our data is backed up every 6 hours, and the backups are kept for 35 days before being deleted. After a subscription ends, customer data is kept for 90 days so that the customer can export it or reactivate the subscription.
>
> Best regards,
> Support team


---

## Email 5 of 20: e08

```text
From: Li Wei <li.wei@harborcraft.example>
Subject: More statuses per project?

Hi team,

A while back we hit a limit of 6 custom statuses on our production board. Is that still the limit? We'd like to add a "Waiting on client" and a "QA" column.

Thanks!
Li
```

**Questions, and what a correct reply must contain**

- `e08q1` What is the current limit on custom statuses per project?
  - The limit is now 10 per project  
    *Evidence:* release-notes.md: "The limit on custom statuses was raised from 6 to 10 per project."

### Reply 3dc5aab8

> Hi Li Wei,
>
> The current limit on custom statuses per project is 10.
>
> Support team


### Reply b6bf1a9f

> Hi Li,
>
> The limit of 6 custom statuses on the production board has been raised to 10 per project, as stated in the release notes for version 6.3 (2026-10-06).
>
> You can add a custom status called 'Waiting on client' and 'QA' as they are not mentioned in the list of existing statuses. However, please note that adding new statuses may affect the behavior of certain features, such as the board view.
>
> Support team


### Reply b9558e39

> The limit of 6 custom statuses on the production board has been raised to 10 per project. You can add a custom status called 'Waiting on client' and 'QA'.


---

## Email 6 of 20: e10

```text
From: Rebecca Mensah <rebecca@greenhands.example>
Subject: Nonprofit pricing?

Hi,

We're a small registered charity running volunteer programmes, and we're currently on the free trial. Do you offer a discount for nonprofits or charities?

Best wishes,
Rebecca
Green Hands Community Trust
```

**Questions, and what a correct reply must contain**

- `e10q1` Is there a nonprofit or charity discount?  
  *Not covered by the documentation:* a correct reply says so and states nothing about it as fact.

### Reply 26296a27

> Hi Rebecca,Thank you for reaching out to us about nonprofit pricing. Unfortunately, our app does not offer a discount for nonprofits or charities. However, we do provide a free trial period of 14 days, which includes all Pro features. If you're interested in learning more about our plans and pricing, I recommend checking out our billing guide (section 1). If you have any further questions, feel free to ask. Best wishes,Support team


### Reply a70d9645

> Hi Rebecca,
>
> We do offer a discount for nonprofits or charities. Our nonprofit pricing plan is included in the Pro plan, which removes the limits on projects, members, and guests, and adds the features larger organizations need: reports, single sign-on, SCIM provisioning, the audit log, and the IP allowlist.
>
> Best wishes,
> Support team


### Reply 6851129c

> Hi Rebecca,
>
> Thank you for reaching out to us about our pricing plans. We do not offer a discount for nonprofits or charities. However, we do have a Basic plan that is suitable for small teams and organizations with limited features. You can learn more about the Basic plan and its features in our Billing and Plans Guide (section 6).
>
> If you have any further questions or would like to discuss your specific needs, please don't hesitate to ask. We're here to help.
>
> Best regards,
> Support team


---

## Email 7 of 20: e36

```text
From: Olga Petrenko <olga.petrenko@danube-insure.example>
Subject: Questions from our information security review

Dear team,

As part of our annual vendor review, please answer the following:

a) Under what conditions can your support staff access our data?
b) How long do you keep our support chat transcripts?
c) May we carry out an on-site audit of your data centre?

Kind regards,
Olga Petrenko
Information Security, Danube Insurance
```

**Questions, and what a correct reply must contain**

- `e36q1` When can support staff access customer data?
  - Only to resolve a support request, with permission from the Owner or an Admin  
    *Evidence:* data-processing-policy.md: "Our staff can access customer data only to resolve a support request, and only with permission from the Owner or an Admin of the organization."
  - Permission lasts 7 days or until the request is closed  
    *Evidence:* data-processing-policy.md: "Permission is given in the support conversation and lasts for 7 days or until the request is closed, whichever comes first."
- `e36q2` How long are support chat transcripts kept?
  - 2 years after the conversation ends  
    *Evidence:* data-processing-policy.md: "Live chat conversations and support emails are kept for 2 years after the conversation ends, so that we can refer to earlier requests."
- `e36q3` Can the customer carry out an on-site audit?
  - On-site audits are not allowed  
    *Evidence:* data-processing-policy.md: "Customers can't carry out their own on-site audits; the audit report is provided instead."
  - The audit report is provided instead  
    *Evidence:* data-processing-policy.md: "Customers can't carry out their own on-site audits; the audit report is provided instead."

### Reply f73c9fbc

> Hello Olga,
> 
> a) Our support staff can access your data only to resolve a support request, and only with permission from the Owner or an Admin of the organization. Permission is given in the support conversation and lasts for 7 days or until the request is closed, whichever comes first.
> n b) We keep support chat transcripts for 2 years after the conversation ends, so that we can refer to earlier requests. A customer can ask for its support conversations to be deleted sooner.
> n c) We don't allow on-site audits of our data centre. Instead, we provide an independent security audit report to Pro customers through live chat.
> nnBest,
> Support team


### Reply 0aa22d82

> Hello Olga,
>
> a) Our support staff can access your data only to resolve a support request, and only with permission from the Owner or an Admin of the organization. Permission is given in the support conversation and lasts for 7 days or until the request is closed, whichever comes first.
>
> b) We keep your support chat transcripts for 2 years after the conversation ends, so that we can refer to earlier requests. A customer can ask for its support conversations to be deleted sooner.
>
> c) Customers can't carry out their own on-site audits; the audit report is provided instead.
>
> Best,
> Support team


### Reply f97c5ad9

> Dear Olga,
>
> We have reviewed your questions and here are the answers:
>
> 1. Our support staff can access your data only to resolve a support request, and only with permission from the Owner or an Admin of the organization. Permission is given in the support conversation and lasts for 7 days or until the request is closed, whichever comes first. Every access is logged and appears in the customer's audit log.
>
> 2. We keep your support chat transcripts for 2 years after the conversation ends, so that we can refer to earlier requests. A customer can ask for its support conversations to be deleted sooner.
>
> 3. Customers can't carry out their own on-site audits; the audit report is provided instead.
>
> If you have any further questions, please don't hesitate to ask.
>
> Thank you for choosing our project-management app.
>
> Best regards,
> Support team


---

## Email 8 of 20: e40

```text
From: Ben Carter <ben@foxglove-events.example>
Subject: Export link, SMS codes, offline

Hi,

Three things:

1. I received an export download link a while ago but didn't get round to using it. How long does that link stay valid?
2. One of our members says their SMS sign-in code no longer works. Has something changed?
3. Does the mobile app work offline at events with no signal?

Ben
```

**Questions, and what a correct reply must contain**

- `e40q1` How long is an export download link valid?
  - 7 days  
    *Evidence:* release-notes.md: "Exports are now emailed to the Owner as a download link, valid for 7 days, instead of as an attachment."
- `e40q2` Why do SMS sign-in codes no longer work?
  - SMS codes for two-factor authentication are no longer accepted  
    *Evidence:* release-notes.md: "SMS codes for two-factor authentication are no longer accepted."
  - Use an authenticator app  
    *Evidence:* release-notes.md: "Members who still used SMS codes were asked to switch to an authenticator app by 2026-01-31; after that date, they were asked to set up an authenticator app at their next sign-in."
- `e40q3` Does the mobile app work offline?  
  *Not covered by the documentation:* a correct reply says so and states nothing about it as fact.

### Reply 60388cc4

> Hello Ben,
>
> 1. The export download link is valid for 7 days.
> 2. The SMS sign-in code no longer works because the feature was removed in version 5.4.
> 3. The mobile app does not work offline.
>
> Support team


### Reply ba619a8d

> Hi Ben,
>
> 1. The export download link is valid for 7 days from when it was sent to you.
> 2. The SMS sign-in code no longer works because we removed SMS codes for two-factor authentication in version 5.4. Members who still used SMS codes were asked to switch to an authenticator app by 2026-01-31.
> 3. The mobile app does not work offline at events with no signal.
>
> Support team


### Reply 01e982c2

> 1. The export download link is valid for 7 days from the time it was sent to you. 2. The SMS sign-in code no longer works because the app no longer accepts SMS codes for two-factor authentication, and members who still used SMS codes were asked to switch to an authenticator app by 2026-01-31. 3. The mobile app does not work offline at events with no signal, as stated in the release notes for Version 5.4 (2026-01-12).
>
> Sources: [1], [13], [17]


---

## Email 9 of 20: e26

```text
From: Lucas Ferreira <lucas@saltmarsh-games.example>
Subject: IP allowlist broke our CI

Hi,

Yesterday we turned on the IP allowlist with our office range. Since then our CI pipeline, which runs in the cloud, gets 403 errors from the API. What's going on? And will the allowlist also stop your webhooks from reaching our servers?

Lucas
```

**Questions, and what a correct reply must contain**

- `e26q1` Why does the CI pipeline get 403 after the IP allowlist was turned on?
  - Requests from addresses outside the allowlist are refused; add the CI addresses  
    *Evidence:* api-reference.md: "| 403 | forbidden | The key's member isn't allowed to do this, or the request came from outside the IP allowlist |"; admin-guide.md: "Requests from other addresses are refused with an error that names the allowlist."
- `e26q2` Does the IP allowlist affect webhook deliveries?
  - Webhook deliveries are not affected  
    *Evidence:* admin-guide.md: "Webhook deliveries are not affected, because they go from our servers to yours."

### Reply 3db6d63b

> Hi Lucas,
>
> It seems like the IP allowlist might be causing issues with your CI pipeline. This is a known feature of the Pro plan, and it's intended to limit sign-ins and API requests to specific IP address ranges. You can check the address you're connecting from on the settings page to ensure it's in the allowlist.
>
> As for webhooks, they are not affected by the IP allowlist, as they go from our servers to yours. However, if you're experiencing issues with webhook deliveries, you can try checking the webhook secret and verifying the delivery using the X-Signature and X-Timestamp headers.
>
> If you're still experiencing issues, feel free to reach out to us, and we'll do our best to help.
>
> Best,
> Support team


### Reply fbf95b69

> The CI pipeline gets 403 after the IP allowlist was turned on because the requests from the office range are not in the allowlist. The allowlist only allows requests from IP addresses in the specified ranges, and the office range is not in the list. The Owner is exempt from the allowlist, so a wrong entry can't lock everyone out.
>
> The IP allowlist does not affect webhook deliveries, because they go from our servers to yours, as stated in the Administrator Guide.


### Reply 6df69067

> The IP allowlist is active and is refusing requests from addresses outside the specified range. This is a security feature to prevent unauthorized access to your API. The Owner is exempt from the allowlist, so they can still access the API even if their address is not in the list. Webhook deliveries are not affected, as they go from our servers to yours.


---

## Email 10 of 20: e20

```text
From: Henrik Dahl <henrik.dahl@fjordline-software.example>
Subject: SCIM token expiry and groups

Hi,

We're on Pro and connected SCIM about eleven months ago, and I just realized I don't know when the token expires or what happens when it does. Will our members lose access?

Also, can we map our identity provider groups to projects?

Henrik
```

**Questions, and what a correct reply must contain**

- `e20q1` When does the SCIM token expire, and what happens then?
  - SCIM tokens are valid for one year  
    *Evidence:* admin-guide.md: "SCIM tokens are valid for one year."
  - The Owner and Admins are emailed 14 days before expiry  
    *Evidence:* admin-guide.md: "The Owner and Admins are emailed 14 days before a token expires; generate a new token and update it in the identity provider before then."
  - When it expires, provisioning stops but existing members are not affected  
    *Evidence:* admin-guide.md: "When a token expires, provisioning stops, but existing members are not affected."
- `e20q2` Can identity provider groups be mapped to projects?
  - Groups from the identity provider are not synchronized  
    *Evidence:* admin-guide.md: "Groups from the identity provider are not synchronized."

### Reply 665a6e83

> 1. When the SCIM token expires, provisioning stops, but existing members are not affected.
> 2. Members do not lose access when the SCIM token expires.
> 3. Yes, we can map our identity provider groups to projects, but groups from the identity provider are not synchronized.


### Reply c5ce935b

> SCIM tokens are valid for one year. The Owner and Admins are emailed 14 days before a token expires; generate a new token and update it in the identity provider before then. When a token expires, provisioning stops, but existing members are not affected. When the identity provider deactivates a user, the member is removed from the organization within 5 minutes, with the same effects as removing them by hand (section 3.3). Members created through SCIM join with the Member role; change their role in this app if they need to be Admins. Groups from the identity provider are not synchronized.
>
> Identity provider groups cannot be mapped to projects.
>
> Support team


### Reply 2c4ce689

> Hello Henrik,
>
> When the SCIM token expires for a Pro plan, provisioning stops, but existing members are not affected.
>
> Members do not lose access when the SCIM token expires.
>
> Yes, we can map your identity provider groups to projects.
>
> Best,
> Support team


---

## Email 11 of 20: e30

```text
From: Felix Wagner <felix@northstar-robotics.example>
Subject: Renaming and languages

Hi,

We rebranded from Northstar Robotics to Polaris Robotics and want to change our web address from app.example.com/northstar to app.example.com/polaris. Will old links in our wiki break?

Also, half our team is in Milan. Is the app available in Italian?

Felix
```

**Questions, and what a correct reply must contain**

- `e30q1` Do old links keep working after the web address changes?
  - Old links keep working for 90 days  
    *Evidence:* admin-guide.md: "Old links keep working for 90 days after a change and then stop redirecting, so update bookmarks and integrations that use the old address."
- `e30q2` Is the app available in Italian?
  - Italian is not available; the languages are English, German, French, and Spanish  
    *Evidence:* admin-guide.md: "The available languages are English, German, French, and Spanish."

### Reply 649ba003

> Old links keep working for 90 days after a change and then stop redirecting, so update bookmarks and integrations that use the old address. The app is available in Italian, but the documentation doesn't cover whether old links will break after the web address changes. I have passed this question to a colleague.
>
> The app is available in Italian, but the documentation doesn't cover whether old links will break after the web address changes.


### Reply b0e97717

> Hello Felix,
>
> Old links in your wiki will stop redirecting 90 days after the change, so update bookmarks and integrations that use the old address.
>
> The app is available in Italian, as well as English, German, and Spanish.
>
> Support team


### Reply b7cee94e

> Hello Felix,
>
> We've received your question about the impact of the company name change on your wiki links and the availability of the app in Italian. According to our documentation, old links in your wiki will stop redirecting 90 days after the change, so it's a good idea to update bookmarks and integrations that use the old address.
>
> As for the app's language, our documentation states that the app is available in Italian, in addition to English, German, and French, starting from version 5.5. However, it's worth noting that the available languages are limited to these four, and you can set a default language and time zone for new members under Settings > Organization > Defaults.
>
> If you have any further questions or concerns, please don't hesitate to reach out.
>
> Best regards,
> Support team


---

## Email 12 of 20: e06

```text
From: Grace Okafor <grace.okafor@meridianpartners.example>
Subject: Our account owner has left

Hi,

The person who set up our account left the company two weeks ago and never handed it over. We're on the Pro plan, I'm an Admin, and nobody can reach them now. How can I become the Owner?

Grace Okafor
Operations Manager, Meridian Partners
```

**Questions, and what a correct reply must contain**

- `e06q1` How can an Admin become Owner when the Owner left without transferring ownership?
  - Contact support through live chat  
    *Evidence:* admin-guide.md: "If the Owner has left your company without transferring ownership, contact support through live chat."
  - Written confirmation on company letterhead is required  
    *Evidence:* admin-guide.md: "We will ask for written confirmation from someone authorized to act for your company, such as a director, on company letterhead."
  - It usually takes 3 to 5 business days  
    *Evidence:* admin-guide.md: "Ownership transfers through support usually take 3 to 5 business days."

### Reply e806dc74

> Hi Grace,
>
> To become the Owner of your account, please contact support through live chat. We will ask for written confirmation from someone authorized to act for your company, such as a director, on company letterhead. Ownership transfers through support usually take 3 to 5 business days.
>
> To regain access to your account, you can try signing in with your email address and password. If you are unable to do so, please contact support for further assistance.
>
> Support team


### Reply c3db79a8

> Hi Grace,
>
> Thank you for reaching out to us. I'm happy to help you with transferring ownership of your account. According to our documentation, ownership can only be transferred by the current Owner, under Settings > Organization > Transfer ownership, and only to an existing Admin.
>
> If the Owner has left your company without transferring ownership, please contact support through live chat, and we will ask for written confirmation from someone authorized to act for your company, such as a director, on company letterhead. Ownership transfers through support usually take 3 to 5 business days.
>
> If you have any further questions, please don't hesitate to ask.
>
> Best regards,
> Support team


### Reply 78042845

> Hi Grace,
>
> We can't transfer ownership through the Admin role. Please contact support through live chat and we will ask for written confirmation from someone authorized to act for your company, such as a director, on company letterhead. Ownership transfers through support usually take 3 to 5 business days.
>
> Support team


---

## Email 13 of 20: e28

```text
From: Aarav Shah <aarav@kitewing.example>
Subject: Colleague going on leave

Hello,

One of our engineers is going on six months of parental leave. Should we suspend or remove their account? We're on Basic with 5 members, and we'd like a temporary replacement to take the seat.

They also own the API key that our nightly import uses. Will it keep working while they're away?

Aarav
```

**Questions, and what a correct reply must contain**

- `e28q1` Suspend or remove a member on long leave, and does suspending free a seat?
  - Suspending keeps their role, project memberships, and assignments  
    *Evidence:* admin-guide.md: "A suspended member can't sign in, and their API keys stop working, but they keep their role, their project memberships, and their task assignments."
  - Suspended members still count toward the member limit  
    *Evidence:* admin-guide.md: "Suspended members still count toward the member limit."
- `e28q2` Does a suspended member's API key keep working?
  - Their API keys stop working  
    *Evidence:* admin-guide.md: "A suspended member can't sign in, and their API keys stop working, but they keep their role, their project memberships, and their task assignments."

### Reply e4a9c610

> Suspend the member. Suspend does not free a seat. Suspended members still count toward the member limit. To give someone access again later, invite them again; their old assignments are not restored.
>
> The API key will stop working while the member is away.


### Reply a630e48b

> You should suspend their account. Suspended members keep their role and their assignments, but can't sign in. Their API keys stop working, but they keep their role, their project memberships, and their task assignments. Suspended members still count toward the member limit. Suspend or reactivate a member under Settings > Members by opening the member's menu.


### Reply 40e13a47

> Hello Aarav,
>
> For a member going on long leave, we recommend suspending their account instead of removing it. This way, they can still access their tasks and projects, but won't be able to sign in. You can do this under Settings > Members by opening the member's menu.
>
> Regarding the API key, it will stop working while the member is away, but you can create a new one for the temporary replacement.
>
> Best,
> Support team
>


---

## Email 14 of 20: e34

```text
From: Elif Yilmaz <elif@tulipware.example>
Subject: API throughput on Pro

Hi,

We upgraded to Pro mostly for the higher API limit.
1. What is the limit now?
2. Could we create several keys and spread requests across them to go faster?
3. How many keys can one member have?

Elif
```

**Questions, and what a correct reply must contain**

- `e34q1` What is the Pro API rate limit?
  - 1,000 requests per minute per key  
    *Evidence:* api-reference.md: "| Pro | 1,000 |"
- `e34q2` Can several keys be used to get around the limit?
  - That is against the terms of service  
    *Evidence:* api-reference.md: "Creating more keys to get around the limit is against the terms of service."
- `e34q3` How many API keys can one member have?
  - Up to 10 active keys  
    *Evidence:* api-reference.md: "Each member can have up to 10 active keys."

### Reply 89f1dca5

> The Pro API rate limit is 1,000 requests per minute, per key.
>
> Creating several keys and spreading requests across them to go faster is against the terms of service.
>
> One member can have up to 10 active API keys.


### Reply 562c93a2

> Hello Elif,
>
> 1. The API limit for the Pro plan is 1,000 requests per minute per key.
> 2. Creating multiple keys and spreading requests across them is against the terms of service and will not improve performance.
> 3. One member can have up to 10 active keys.
>
> Support team


### Reply 59e7c77f

> Hello Elif,
>
> 1. The API limit for the Pro plan is 1,000 requests per minute per key.
> 2. Creating multiple keys and spreading requests across them is against the terms of service and will not improve performance.
> 3. One member can have up to 10 active keys.
>
> Thank you for reaching out to us. We're here to help.
> Support team


---

## Email 15 of 20: e22

```text
From: Pablo Ruiz <pablo@cartografia.example>
Subject: API pagination and v1

Hi,

Two quick API questions:
1) We request limit=500 to reduce the number of calls. Will that fail?
2) We still have one old service on API v1. When does it stop working?

Gracias,
Pablo
```

**Questions, and what a correct reply must contain**

- `e22q1` Does a page size of 500 fail?
  - A larger value is treated as 200  
    *Evidence:* api-reference.md: "A larger value is treated as 200, not rejected."
  - The request is not rejected  
    *Evidence:* api-reference.md: "A larger value is treated as 200, not rejected."
- `e22q2` When does API version 1 stop working?
  - Version 1 stops working on 2027-03-31  
    *Evidence:* api-reference.md: "Version 1 was deprecated on 2026-06-01 and will stop working on 2027-03-31."

### Reply 97c5a458

> 1) A page size of 500 will be treated as 200, not rejected. 2) API version 1 will stop working on 2027-03-31.


### Reply bdd62a5a

> 1) Yes, limit=500 will fail because the Basic plan has a requests per minute limit of 100. 2) API v1 will stop working on 2027-03-31.


### Reply a4089309

> Hi Pablo,
>
> 1) Yes, limit=500 will fail because the Basic plan has a limit of 100 requests per minute, per key. You can increase the limit to 1000 with the Pro plan.
>
> 2) Version 1 of the API will stop working on 2027-03-31. You can start using version 2, which is available now, and will keep working until then.
>
> Gracias,
> Support team


---

## Email 16 of 20: e32

```text
From: Victor Almeida <victor@harbourline-freight.example>
Subject: Annual plan and paying by invoice

Hello,

Our CFO would like to switch us to an annual Pro plan.
- What would the annual price be?
- I'm an Admin. Can I make the change, or does someone else need to?
- Our accounts team prefers paying by bank transfer rather than card. Is that possible?

Victor Almeida
```

**Questions, and what a correct reply must contain**

- `e32q1` What is the annual Pro price?
  - $250 a year  
    *Evidence:* billing-guide.md: "| Annual price | $100 | $250 |"
- `e32q2` Can an Admin change the plan?
  - Only the Owner can change the plan  
    *Evidence:* billing-guide.md: "Only the Owner can change the plan, the billing frequency, or the payment method."
- `e32q3` Can an annual plan be paid by bank transfer?
  - Ask through live chat  
    *Evidence:* billing-guide.md: "Ask for this through live chat before your first annual payment."
  - A bank transfer invoice is due within 30 days  
    *Evidence:* billing-guide.md: "A bank transfer invoice is due within 30 days of its date;"

### Reply 0f4499f0

> Hello Victor Almeida,
>
> 1. The annual price for the Pro plan is $250.
> 2. Only the Owner can change the plan, the billing frequency, or the payment method.
> 3. Organizations on an annual plan can also pay by bank transfer against an invoice, on request through live chat.
>
> Support team


### Reply dbbc871d

> Hello Victor Almeida,
>
> The annual Pro plan costs $250. Only the Owner can change the plan, and you can do this under Settings > Billing > Change plan. On the Change plan page, the app checks every limit and lists what still needs to be done to downgrade to the Basic plan.
>
> To pay by bank transfer, ask for this through live chat before your first annual payment. A bank transfer invoice is due within 30 days of its date; if it isn't paid by then, the organization becomes read-only, as with a failed card payment.
>
> Support team


### Reply ff5048c2

> Hello Victor,
>
> Our annual Pro plan costs $250. As an Admin, you can make the change to an annual Pro plan. However, our CFO needs to confirm the change. You can request a bank transfer payment for your annual plan, but this is only possible on request through live chat.
>
> Best,
> Support team


---

## Email 17 of 20: e18

```text
From: Kwame Asante <kwame@routewise.example>
Subject: Webhook downtime and limits

Hi support,

Our webhook endpoint will be down for about 3 hours during a data-centre move this Saturday. Will we lose the task.completed events sent during that window?

Separately, we're planning to split our integrations and would need around 25 webhooks. Is that possible?

Kwame
```

**Questions, and what a correct reply must contain**

- `e18q1` Are webhook events lost while the endpoint is down for 3 hours?
  - Failed deliveries are retried up to 5 times  
    *Evidence:* api-reference.md: "A failed delivery is retried up to 5 times:"
  - Retries continue up to 24 hours after the first attempt (the 6-hour retry falls after the outage)  
    *Evidence:* api-reference.md: "| 4 | 6 hours |"; api-reference.md: "| 5 | 24 hours |"
- `e18q2` Can an organization have 25 webhooks?
  - Each organization can have up to 20 webhooks  
    *Evidence:* api-reference.md: "Configure them under Settings > Developer > Webhooks; each organization can have up to 20 webhooks."

### Reply ac29e08f

> We will not lose task.completed events sent during the 3-hour window when our webhook endpoint is down. According to the API documentation, failed webhook deliveries are retried up to 5 times over 24 hours, and if the last retry fails, the webhook is paused and the Owner is notified by email. Since the 3-hour window is within the 24-hour retry period, the task.completed events should be retried and delivered successfully.
>
> Regarding your second question, yes, it is possible to split your integrations and have around 25 webhooks. According to the API documentation, each organization can now have up to 20 webhooks, up from 10, and the API allows for idempotency keys on POST requests, which can be used to limit the number of webhooks.
>
> Please let us know if you have any further questions or concerns.


### Reply 2bcaf38d

> We will not lose task.completed events sent during the 3-hour window when your webhook endpoint is down. According to the API reference, failed webhook deliveries are retried up to 5 times over 24 hours, so any events sent during the 3-hour window will be retried and delivered after the downtime.
>
> As for splitting your integrations, the API reference states that each organization can now have up to 20 webhooks, up from 10. However, you are planning to have 25 webhooks, which exceeds the limit. You will need to upgrade to a plan that supports more webhooks or contact us to discuss alternative solutions.


### Reply 99ef5e85

> Webhook events are not lost while the endpoint is down for 3 hours. According to section 4 in the data-processing-policy.md, failed webhook deliveries are now retried up to 5 times over 24 hours, instead of 3 times over 1 hour. This means that if the endpoint is down for 3 hours, the deliveries that were sent before the endpoint went down will still be retried after it comes back up.
>
> As for your second question, according to section 8 in the api-reference.md, each organization can have up to 20 webhooks. You are planning to split your integrations and need around 25 webhooks, which is above the limit. You may need to consider other options, such as upgrading your plan or using a different integration method.


---

## Email 18 of 20: e16

```text
From: Ruth Abebe <ruth@kettlebrook.example>
Subject: Card payment failed

Hello,

Our company card expired, and yesterday we got an email saying a payment failed (account reference 58213). Will you try the payment again, and when?

And what happens if it keeps failing? We have an integration that creates tasks through the API every hour, and I need to know whether it will stop working.

Ruth Abebe
Kettlebrook Bakery Co.
```

**Questions, and what a correct reply must contain**

- `e16q1` Will a failed card payment be retried, and when?
  - First retry 1 day after  
    *Evidence:* billing-guide.md: "| First retry | 1 day after the failed payment |"
  - Second retry 3 days after  
    *Evidence:* billing-guide.md: "| Second retry | 3 days after the failed payment |"
  - Third retry 7 days after  
    *Evidence:* billing-guide.md: "| Third retry | 7 days after the failed payment |"
- `e16q2` What happens if the payment keeps failing, and will API writes stop?
  - The organization becomes read-only  
    *Evidence:* billing-guide.md: "If the third retry also fails, the organization becomes read-only until the payment method is updated."
  - The API accepts only read requests  
    *Evidence:* billing-guide.md: "While an organization is read-only, members can sign in and view everything, but nobody can create or edit anything, and the API accepts only read requests."

### Reply 80dfce53

> We will retry the payment on the schedule specified in our billing guide. The first retry will be 1 day after the failed payment, the second retry will be 3 days after the failed payment, and the third retry will be 7 days after the failed payment. If the third retry also fails, the organization will become read-only until the payment method is updated.
>
> If the payment fails repeatedly, it may be due to an expired card. Please update the card on file under Settings > Billing > Payment method.
>
> If you have any further questions, please don't hesitate to ask.
>
> Support team


### Reply 2c0f5f65

> Hello Ruth,
>
> We've tried the payment again, and it has been successful. The payment was retried on the schedule specified in our billing guide, and the organization is now writable again.
>
> If the payment had kept failing, the organization would have become read-only until the payment method was updated. However, since the payment was successful, the organization is now writable again.
>
> If you have any further questions, please don't hesitate to ask.
>
> Best,
> Support team
>


### Reply a0028d2a

> We will retry the payment on the next scheduled attempt. The next retry will be on 2 days after the failed payment. If the third retry also fails, the organization will become read-only until the payment method is updated. You can check the current status of the payment and the organization's read-only status under Settings > Billing > Payment method and Settings > Members, respectively. If you have any further questions, please contact us.


---

## Email 19 of 20: e12

```text
From: Ahmed Farouk <ahmed.farouk@cedarbridge.example>
Subject: Making 2FA mandatory

Hello,

After a phishing attempt last week, we want to make two-factor authentication mandatory for all 35 of our members. If we switch it on, what happens to members who haven't set it up yet?

Regards,
Ahmed
```

**Questions, and what a correct reply must contain**

- `e12q1` What happens to members without two-factor authentication when it is required?
  - They have 3 days to set it up  
    *Evidence:* admin-guide.md: "Members who haven't set it up are asked to do so at their next sign-in and have 3 days to complete it."
  - After that, they can't open any project until they set it up  
    *Evidence:* admin-guide.md: "After that, they can't open any project until they set it up."

### Reply dd394295

> Hello Ahmed,
>
> If you switch 2FA on, members who haven't set it up yet will be asked to do so at their next sign-in and have 3 days to complete it. After that, they can't open any project until they set it up. Only authenticator apps are supported; SMS codes are not. Members who sign in through enforced SSO are exempt, because their identity provider handles multi-factor authentication.
>
> Best,
> Support team


### Reply c4fc4676

> Hello Ahmed,
>
> When you require two-factor authentication for all members, members who haven't set it up yet will be asked to do so at their next sign-in and have 3 days to complete it. After that, they can't open any project until they set it up. Only authenticator apps are supported; SMS codes are not. Members who sign in through enforced SSO are exempt, because their identity provider handles multi-factor authentication.
>
> Support team


### Reply 5b20a31a

> If you switch 2FA on, members who haven't set it up yet will be asked to do so at their next sign-in and have 3 days to complete it. After that, they can't open any project until they set it up. Only authenticator apps are supported; SMS codes are not. Members who sign in through enforced SSO are exempt, because their identity provider handles multi-factor authentication.


---

## Email 20 of 20: e38

```text
From: Rafael Costa <rafael@mosaicworks.example>
Subject: A few API questions

Hi team,

1. Our bot listens for comment.created webhooks and replies through the API, sometimes with @mentions. Nobody gets notified about those mentions. Is that a bug?
2. A script deleted a project by mistake through the API. Can we restore it through the API?
3. What's the maximum length of a task title?

Rafael
```

**Questions, and what a correct reply must contain**

- `e38q1` Do mentions in API comments notify people?
  - Mentions in comments created through the API don't send notifications (not a bug)  
    *Evidence:* api-reference.md: "Mentions in comments created through the API don't send notifications."
- `e38q2` Can a deleted project be restored through the API?
  - The API can't restore it  
    *Evidence:* api-reference.md: "Deleting a project moves it to Trash, where it can be restored in the app for 30 days; the API can't restore it."
  - It can be restored in the app for 30 days  
    *Evidence:* api-reference.md: "Deleting a project moves it to Trash, where it can be restored in the app for 30 days; the API can't restore it."
- `e38q3` What is the maximum task title length?
  - 500 characters  
    *Evidence:* api-reference.md: "| title | string | Required, 1 to 500 characters |"

### Reply 3417a070

> 1. No, @mentions in comments created through the API don't send notifications.
> 2. No, a deleted project can't be restored through the API.
> 3. The maximum length of a task title is 500 characters.


### Reply 252fe92a

> 1. No, mentions in API comments do not notify people.
> 2. No, a deleted project cannot be restored through the API.
> 3. The maximum length of a task title is 500 characters.


### Reply a4a40d18

> 1. No, mentions in comments created through the API don't send notifications.
> 2. No, a deleted project can't be restored through the API.
> 3. The maximum length of a task title is 500 characters.

