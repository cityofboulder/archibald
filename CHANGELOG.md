# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Add a suite of exceptions split into those that are raised by the ESRI API (`ArcGISError`) and those raised by the `archie` tool itself (`ArchieClientError`).
- Error handling for quirky ESRI response errors. Functions exist for both parsing ESRI errors (`parse_esri_error()`) and handling ESRI errors for callers as a decorator (`handle_esri_errors()`).
- Base async auth handler class called `ArcGISAuth` that mandates a `get_token()` method in any subclasses.
- User token auth flows, where a user supplies a username and password in exchange for a token from ESRI's generateToken endpoint. Implemented as `UserTokenAuth`.
- Base httpx client that handles authentication, enforces response formatting, and routes get and post requests from any endpoint. Implemented as `ArchieClient`.

[Unreleased]: https://github.com/cityofboulder/archie