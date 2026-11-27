Key Features:

Automated intake form and email notifications.

Streamlined patient information and request collection.

CI pipeline with automated testing to check application functionality and reliability.

Architecture diagram

                 ┌──────────────────────────────────────────┐
                 │          USER (Patient)                  │
                 │                                          │
                 │  - Opens MyNextStepHealth                │
                 │  - Completes health intake form          │
                 │  - Submits personal information          │
                 └──────────────────┬───────────────────────┘
                                    │
                              HTTPS Request
                                    │
                 ┌──────────────────▼───────────────────────┐
                 │          FRONTEND (Web Application)      │
                 │                                          │
                 │  - HTML / CSS / JavaScript               │
                 │  - Intake form                           │
                 │  - Form validation                       │
                 │  - Submission interface                  │
                 └──────────────────┬───────────────────────┘
                                    │
                              API Request
                                    │
                 ┌──────────────────▼───────────────────────┐
                 │          BACKEND (Flask / Python)        │
                 │                                          │
                 │  - Receives form submissions             │
                 │  - Validates incoming information        │
                 │  - Processes patient data                │
                 │  - Handles application logic             │
                 │  - Controls database access              │
                 └──────────┬───────────────┬───────────────┘
                            │               │
                     Store data       Trigger notification
                            │               │
             ┌──────────────▼──────┐  ┌─────▼────────────────┐
             │    DATABASE         │  │   EMAIL SERVICE      │
             │                     │  │                      │
             │  Patient records    │  │  Gmail / SMTP        │
             │  Intake submissions │  │                      │
             │  Submission data    │  │  Sends notification  │
             │                     │  │  when a form is       │
             │  Secure storage     │  │  submitted            │
             └─────────────────────┘  └──────────┬───────────┘
                                                 │
                                           Email notification
                                                 │
                                   ┌─────────────▼───────────┐
                                   │     ADMIN / STAFF       │
                                   │                         │
                                   │  - Receives notification│
                                   │  - Reviews submission   │
                                   │  - Follows up with      │
                                   │    patient              │
                                   └─────────────────────────┘


                 ┌──────────────────────────────────────────┐
                 │             SECURITY LAYER               │
                 │                                          │
                 │  - HTTPS encryption                      │
                 │  - Input validation                      │
                 │  - Authentication and access control     │
                 │  - Secure environment variables          │
                 │  - Restricted access to patient records  │
                 └──────────────────────────────────────────┘
