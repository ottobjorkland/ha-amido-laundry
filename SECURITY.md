# Security policy

* Report vulnerabilities privately via GitHub's "Report a vulnerability" (Security tab) – please do not open a
  public issue with exploit details.
* In scope: handling of credentials/tokens, command or HTML injection, unsafe defaults.
* Never include real credentials, session links, addresses or coordinates in an issue or pull request.

## Design notes
* The card never builds shell commands: it only passes an object id (`\d+-\d+-\d+`), an ISO date and a slot
  index/time to Home Assistant services; the script validates every argument again before use.
* All values originating from the portal are HTML-escaped before they are rendered.
* Secrets live in `chmod 600` files, are never printed and never logged; error output contains only error
  codes and generic messages.
