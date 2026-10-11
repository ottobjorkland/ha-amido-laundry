#!/usr/bin/env bash
# Generic guard against committing real data. Runs in CI; run locally before every push.
set -u
fail=0
bad() { echo "PRIVACY CHECK FAILED: $1"; fail=1; }
files=$(git ls-files | grep -v -E '^(tools/privacy_check.sh|LICENSE|docs/img/)')
# private-network addresses
grep -nE '(^|[^0-9])(192\.168|10\.[0-9]+|172\.(1[6-9]|2[0-9]|3[01]))\.[0-9]+\.[0-9]+' $files && bad "private IP address"
# real-looking apartment parameter (fixtures must use 0000-00000)
grep -nE 'Apartment=[0-9]{3,}-[0-9]+' $files | grep -v '0000-00000' && bad "apartment id that is not the fake 0000-00000"
# token-looking strings
grep -nE '(ghp_|github_pat_|xox[bp]-|AKIA[0-9A-Z]{12})' $files && bad "token-like string"
grep -nE -- '-----BEGIN [A-Z ]*PRIVATE KEY' $files && bad "private key"
# e-mail addresses (the noreply form is fine)
grep -nE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}' $files | grep -v -E 'noreply|example\.(com|invalid)' && bad "e-mail address"
# a credentials file must never be tracked
git ls-files | grep -E '^(amido_credentials|amido_state|amido_cache)\.json$' && bad "secret/state file tracked"
# coordinates with many decimals inside code/docs (examples use 4 decimals and are fictional)
grep -nE '(lat|lon)[^0-9-]{0,6}-?[0-9]{1,3}\.[0-9]{6,}' $files && bad "high-precision coordinates"
[ $fail -eq 0 ] && echo "privacy check: OK"
exit $fail
