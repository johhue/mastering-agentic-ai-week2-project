# Project 4: Customer Support Knowledge Base with Hybrid Search

## Description

Build a customer support bot that combines keyword search and semantic search
(hybrid retrieval) over support tickets, FAQs, and product manuals.

Implement a confidence-based fallback: when the system is not sure of an answer,
it escalates to a human rather than hallucinating.

Test with 20 real-world-style support queries and measure first-contact
resolution rate.

This project is highly relevant for e-commerce, SaaS, and consumer-facing
companies where bad AI answers directly cost customer trust.

## Best For

- Product Managers focused on customer experience
- Software Engineers handling implementation
- Founders building an MVP for their product
- QA Engineers testing edge cases
- Commerce and retail roles

## Deliverable

A working support bot with hybrid search and escalation logic, tested against 20
queries with resolution metrics.

## Submission

- Demo recording
- GitHub link or zip file
- Evaluation metrics document

## Difficulty

Intermediate.

Code and n8n options are acceptable. Engineers may add custom reranking.

## Core Requirements

- Create a data loader script that uploads documents from a folder to a Pinecone
  vector database.
- Build a customer support bot that combines keyword search and semantic search
  over support tickets, FAQs, and product manuals.
- Implement a confidence-based fallback so uncertain answers are escalated to a
  human instead of hallucinated.
- Test with 20 real-world-style support queries.
- Measure first-contact resolution rate.

## Data Set 1: Manuals

You are the CEO of a company called RemindMe, which specializes in custom alarm
and alerting software.

Your company's mission is to ensure people never miss a critical event in their
life.

The software will let users set events and try different reminder mechanisms,
including:

- Alarm on a phone
- Automatically posting to social media that the user needs to be reminded
- Encouraging a friend or co-worker to call or text the user
- Asking a close relative to physically make contact with the user

Create organizational documents in each of these areas:

1. HR Policies
2. Compliance Manuals
3. Legal Disclosures
4. Product Documentation
5. User Guides
6. Help Desk Manuals
7. FAQs

Each document should have the following sections:

- Document Title
- Table of Contents
- Author
- Revision History
- Description
- Sections relevant to the document

Each document should be about 4,096 characters and human readable.

Place the documents in a folder called `Company Manuals`.

## Data Set 2: Data

You are the CEO of a company called RemindMe, which specializes in custom alarm
and alerting software.

Your company's mission is to ensure people never miss a critical event in their
life.

The software will let users set events and try different reminder mechanisms,
including:

- Alarm on a phone
- Automatically posting to social media that the user needs to be reminded
- Encouraging a friend or co-worker to call or text the user
- Asking a close relative to physically make contact with the user

Create mock data for the following operational areas:

- Employee List:
  - Employee Number
  - Job Title
  - Salary
  - SSN
  - Home Address
  - Phone Number
  - Job Title values should include CEO, HR, Sales, QA Engineer, and Software
    Engineer.
- Customer List:
  - Customer Number
  - Date
  - Username
  - First Name
  - Last Name
  - Email address
- Help Desk Tickets:
  - Ticket Number
  - Date
  - Description
  - Severity
  - Username
  - Username should exist in the Customer List.
- Software Variances:
  - Defect Number
  - Date
  - Description
  - Severity
  - DetectedBy
  - DetectedBy should be an employee in the Employee List with the QA Engineer
    role.

Each document should include at least 50 records, be in JSON format, and include
metadata.

Place the documents in a folder called `RemindMe Company Data`.
