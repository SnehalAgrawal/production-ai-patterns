# Labelling worksheet

52 replies to 20 emails.

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

## Email 1 of 20: e26

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

### Reply 48638d0f

> Hi Lucas,
>
> The IP allowlist is currently blocking requests from your office range, causing 403 errors in your CI pipeline. This is a new feature in the Pro plan, which allows admins to limit sign-ins and API requests to specific IP address ranges. The Owner is exempt from the allowlist.
>
> The IP allowlist will not affect webhook deliveries, as they go from our servers to yours.
>
> Support team


### Reply e4a90737

> 1. What's going on with the IP allowlist?


### Reply 6df69067

> The IP allowlist is active and is refusing requests from addresses outside the specified range. This is a security feature to prevent unauthorized access to your API. The Owner is exempt from the allowlist, so they can still access the API even if their address is not in the list. Webhook deliveries are not affected, as they go from our servers to yours.


---

## Email 2 of 20: e38

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

### Reply a4a40d18

> 1. No, mentions in comments created through the API don't send notifications.
> 2. No, a deleted project can't be restored through the API.
> 3. The maximum length of a task title is 500 characters.


### Reply ad507060

> Hi Rafael,
>
> 1. No, @mentions in comment.created webhooks are not enabled for notifications.
> 2. No, deleted projects cannot be restored through the API.
> 3. The maximum length of a task title is 500 characters.
>
> Support team


---

## Email 3 of 20: e16

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


### Reply c849f58e

> We will retry the payment on the next scheduled attempt. The next retry will be on 2 days after the failed payment. If the third retry also fails, the organization will become read-only until the payment method is updated. You can request a refund within 30 days of purchase, through live chat. If the payment keeps failing, your integration will stop working and the organization will become read-only. We have passed this information to a colleague for further assistance.


---

## Email 4 of 20: e30

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

### Reply ccbbf58d

> Hello Felix,
>
> Old links in your wiki will stop redirecting 90 days after the change, so update bookmarks and integrations that use the old address.
>
> The app is available in Italian, as it is one of the languages listed in the available languages section under Settings > Organization > Defaults.
>
> Support team


### Reply b0e97717

> Hello Felix,
>
> Old links in your wiki will stop redirecting 90 days after the change, so update bookmarks and integrations that use the old address.
>
> The app is available in Italian, as well as English, German, and Spanish.
>
> Support team


---

## Email 5 of 20: e28

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

### Reply a630e48b

> You should suspend their account. Suspended members keep their role and their assignments, but can't sign in. Their API keys stop working, but they keep their role, their project memberships, and their task assignments. Suspended members still count toward the member limit. Suspend or reactivate a member under Settings > Members by opening the member's menu.


### Reply 4d0f027c

> Hello Aarav,
>
> For a member going on six months of parental leave, you should suspend their account. This will keep their role, project memberships, and task assignments, but prevent them from signing in and using their API key.
>
> Their data will be kept for 90 days after the subscription ends, and then permanently deleted.
>
> Support team


### Reply 5ac65e90

> We should suspend the engineer's account for six months while they are on parental leave. This will prevent them from accessing their API keys and other sensitive data. We can reactivate the account after the leave period ends.


---

## Email 6 of 20: e24

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

### Reply e9fb156e

> Hi Sophie,
>
> To downgrade to Basic, you need to sort out the following:
> 1. Archive projects until no more than 3 are active.
> 2. Remove or suspend members until no more than 5 remain, including pending invitations.
> 3. Remove guests from any project that has more than 10.
> 4. Delete files until storage is under 10 GB.
>
> The downgrade will take effect at the start of the next billing period.
>
> If you stay on Pro, there is no discount for paying three years upfront.
>
> Support team


### Reply 9a819029

> Hi Sophie,
>
> To downgrade to Basic, you need to archive projects until no more than 3 are active, remove or suspend members until no more than 5 remain, including pending invitations, remove guests from any project that has more than 10, delete files until storage is under 10 GB, and turn off single sign-on, SCIM, and the IP allowlist. The downgrade takes effect at the start of the next billing period.
>
> If you stay on Pro, there is no discount for paying three years upfront.
>
> Support team


---

## Email 7 of 20: e34

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

### Reply 562c93a2

> Hello Elif,
>
> 1. The API limit for the Pro plan is 1,000 requests per minute per key.
> 2. Creating multiple keys and spreading requests across them is against the terms of service and will not improve performance.
> 3. One member can have up to 10 active keys.
>
> Support team


### Reply bf492b5d

> Hi Elif,
>
> 1. The API limit for the Pro plan is 1,000 requests per minute per key.
> 2. Creating multiple keys and spreading requests across them won't speed up your API throughput, as the rate limit applies per key over a rolling window of one minute.
> 3. One member can have up to 10 active keys.
>
> Support team


---

## Email 8 of 20: e12

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

### Reply b6de0314

> Hello Ahmed,
>
> If you switch 2FA on, members who haven't set it up yet will be asked to do so at their next sign-in and have 3 days to complete it. After that, they can't open any project until they set it up. Only authenticator apps are supported; SMS codes are not.
>
> Members who sign in through enforced SSO are exempt, because their identity provider handles multi-factor authentication.
>
> Support team


### Reply 5b20a31a

> If you switch 2FA on, members who haven't set it up yet will be asked to do so at their next sign-in and have 3 days to complete it. After that, they can't open any project until they set it up. Only authenticator apps are supported; SMS codes are not. Members who sign in through enforced SSO are exempt, because their identity provider handles multi-factor authentication.


### Reply c4b18aee

> If we switch 2FA on, what happens to members who haven't set it up yet? Members who haven't set it up are asked to do so at their next sign-in and have 3 days to complete it. After that, they can't open any project until they set it up. Only authenticator apps are supported; SMS codes are not. Members who sign in through enforced SSO are exempt, because their identity provider handles multi-factor authentication.


---

## Email 9 of 20: e14

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

### Reply c28241d0

> Our app backs up your data every 6 hours. Our data processing policy states that backups are kept for 35 days and then deleted. After a subscription ends, customer data is kept for 90 days so that the customer can export it or reactivate the subscription. During that time, you can sign in, export your data, and reactivate the subscription from Settings > Billing. After 90 days, all projects, tasks, and files are permanently deleted.


---

## Email 10 of 20: e10

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

### Reply a70d9645

> Hi Rebecca,
>
> We do offer a discount for nonprofits or charities. Our nonprofit pricing plan is included in the Pro plan, which removes the limits on projects, members, and guests, and adds the features larger organizations need: reports, single sign-on, SCIM provisioning, the audit log, and the IP allowlist.
>
> Best wishes,
> Support team


### Reply a7216e8e

> We do not offer a discount for nonprofits or charities. However, we do offer a free trial for all organizations, which includes all Pro features.


### Reply b74a82df

> Hi Rebecca,
>
> We do not offer a discount for nonprofits or charities. Our pricing plans are as follows:
>
> The Basic plan is meant for small teams that work on a few projects at a time. It includes up to 3 active projects and 5 members, and each project can have up to 10 guests. Pending invitations count toward the member limit.
>
> Everything in the app works on this plan except the features marked Pro in the table above. The API is fully available, with a lower rate limit. When the organization reaches its storage limit, new uploads are blocked until files are deleted or the plan is upgraded; nothing that is already stored is removed.
>
> The Pro plan removes the limits on projects, members, and guests, and adds the features larger organizations need: reports, single sign-on, SCIM provisioning, the audit log, and the IP allowlist. Support conversations from Pro organizations are answered first. Pro organizations can also request the latest independent security audit report through live chat.
>
> If you have any further questions, please let me know.
>
> Best,
> Support team


---

## Email 11 of 20: e08

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

### Reply bbaea243

> 1. Is the limit of 6 custom statuses on the production board still in effect?
> 2. Can we add a custom status called 'Waiting on client'?
> 3. Can we add a custom status called 'QA'?
>


### Reply b9558e39

> The limit of 6 custom statuses on the production board has been raised to 10 per project. You can add a custom status called 'Waiting on client' and 'QA'.


### Reply 3262a05e

> The limit on custom statuses was raised from 6 to 10 per project. You can add a custom status called 'Waiting on client' and 'QA'.


---

## Email 12 of 20: e32

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


### Reply 4c5f4375

> Hello Victor Almeida,
>
> The annual price for the Pro plan is $250.
>
> To make the change, you need to contact our support team, as only the Owner can make changes to the billing plan.
>
> You can pay by bank transfer instead of card, but you need to request it through live chat before your first annual payment.
>
> Support team


---

## Email 13 of 20: e40

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

### Reply 27ea7133

> 1. How long does the export download link stay valid?
> 2. Has something changed with the SMS sign-in code?
> 3. Does the mobile app work offline at events with no signal?
>


### Reply 01e982c2

> 1. The export download link is valid for 7 days from the time it was sent to you. 2. The SMS sign-in code no longer works because the app no longer accepts SMS codes for two-factor authentication, and members who still used SMS codes were asked to switch to an authenticator app by 2026-01-31. 3. The mobile app does not work offline at events with no signal, as stated in the release notes for Version 5.4 (2026-01-12).
>
> Sources: [1], [13], [17]


### Reply 968a758a

> Hi Ben,
>
> 1. The export download link is valid for 7 days.
> 2. The SMS sign-in code no longer works because SMS codes for two-factor authentication were removed in version 5.4.
> 3. The mobile app does not work offline at events with no signal.
>
> Support team


---

## Email 14 of 20: e18

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

### Reply 578bc564

> Will we lose the task.completed events sent during the 3-hour window when our webhook endpoint is down?


### Reply 4dc2978f

> We will not lose task.completed events sent during the 3-hour window when your webhook endpoint is down. According to [8], failed webhook deliveries are retried up to 5 times over 24 hours, and deliveries can arrive more than once and out of order, so use the delivery ID to ignore duplicates. The 3-hour window is within the 24-hour retry period, so the events will be retried and delivered after the endpoint is back online.


### Reply 2bcaf38d

> We will not lose task.completed events sent during the 3-hour window when your webhook endpoint is down. According to the API reference, failed webhook deliveries are retried up to 5 times over 24 hours, so any events sent during the 3-hour window will be retried and delivered after the downtime.
>
> As for splitting your integrations, the API reference states that each organization can now have up to 20 webhooks, up from 10. However, you are planning to have 25 webhooks, which exceeds the limit. You will need to upgrade to a plan that supports more webhooks or contact us to discuss alternative solutions.


---

## Email 15 of 20: e36

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

### Reply fa8e5678

> 1. What conditions allow your support staff to access our data?


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


### Reply 593c7b7e

> Dear Olga,
>
> a) Our support staff can access your data only to resolve a support request, and only with permission from the Owner or an Admin of the organization. Permission is given in the support conversation and lasts for 7 days or until the request is closed, whichever comes first.
>
> b) Live chat conversations and support emails are kept for 2 years after the conversation ends, so that we can refer to earlier requests. A customer can ask for its support conversations to be deleted sooner.
>
> c) Customers can't carry out their own on-site audits; the audit report is provided instead.
>
> Support team


---

## Email 16 of 20: e06

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


### Reply b48363f3

> Hi Grace,
>
> We will ask for written confirmation from someone authorized to act for your company, such as a director, on company letterhead. Ownership transfers through support usually take 3 to 5 business days.
>
> Support team


### Reply ac5c51c6

> To become the Owner of our account, you need to contact support through live chat and provide written confirmation from someone authorized to act for your company, such as a director, on company letterhead. Ownership transfers through support usually take 3 to 5 business days.


---

## Email 17 of 20: e20

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


### Reply 2ba83d5c

> When the SCIM token expires for a Pro plan, provisioning stops, but existing members are not affected. When the identity provider deactivates a user, the member is removed from the organization within 5 minutes, with the same effects as removing them by hand. Members created through SCIM join with the Member role; change their role in this app if they need to be Admins. Groups from the identity provider are not synchronized.
>
> Members do not lose access when the SCIM token expires. However, if the identity provider deactivates a user, the member is removed from the organization within 5 minutes, with the same effects as removing them by hand.
>
> We can map our identity provider groups to projects, but only if the identity provider maps the groups to the same email address as the members in this app. This is not currently supported, but it is planned for future releases.


### Reply 5d49c17c

> 1. What happens when the SCIM token expires for a Pro plan?
>


---

## Email 18 of 20: e02

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

### Reply 8f4d8f3d

> 1. What does SSO-103 mean?
> 2. How do we fix the SSO login error for Aiyana?
> 3. Why does Aiyana get SSO-103 when she tries to sign in through Okta?
> 4. Documentation excerpts:
> [1](admin-guide.md)
> [2](admin-guide.md)
> [3](admin-guide.md)
> [4](admin-guide.md)
> [5](release-notes.md)
> [6](admin-guide.md)
> [7](api-reference.md)
> [8](release-notes.md)
> [9](admin-guide.md)
> [10](admin-guide.md)
> [11](data-processing-policy.md)
> [12](admin-guide.md)
> [13](admin-guide.md)
> [14](release-notes.md)
> [15](release-notes.md)
> [16](admin-guide.md)
> [17](billing-guide.md)
> [18](release-notes.md)
> [19](release-notes.md)


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


### Reply c197a44d

> Hello Tomás,
>
> The error code SSO-103 means that the email address doesn't match any member. You can try inviting Aiyana or checking the NameID format (step 3 in the administrator guide).
>
> To fix the SSO login error for Aiyana, invite her in the identity provider (step 5 in the administrator guide).
>
> Aiyana gets SSO-103 when she tries to sign in through Okta because her email address doesn't match any member. You can try inviting her or checking the NameID format.
>
> Support team


---

## Email 19 of 20: e04

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

### Reply 438edfbf

> We notify the Owner within 48 hours of becoming aware of a breach of security that affects customer data.


### Reply 07c19dc8

> We will notify you about a personal data breach affecting your data within 48 hours, as stated in our data processing policy.


### Reply 45d2912f

> We will notify you about a personal data breach affecting your data within 48 hours, as stated in our data processing policy. If information isn't available yet, we will send it as soon as it is, without waiting for a complete report. We help the customer decide whether to notify the authorities and the people affected.


---

## Email 20 of 20: e22

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

### Reply e17eca84

> Will limit=500 fail?
>
> 1. Yes, it will fail. According to the API reference, the rate limit applies per API key, over a rolling window of one minute.
>
> 2. When does API v1 stop working?
>
> 1. It will stop working on 2027-03-31. According to the release notes, version 1 of the API is deprecated and will stop working on that date.


### Reply bdd62a5a

> 1) Yes, limit=500 will fail because the Basic plan has a requests per minute limit of 100. 2) API v1 will stop working on 2027-03-31.


### Reply 47a76f3a

> Hello Pablo,
>
> 1) Yes, limit=500 will fail because the Basic plan has a rate limit of 100 requests per minute, per key.
> 2) Version 1 of the API will stop working on 2027-03-31.
>
> Gracias,
> Support team

