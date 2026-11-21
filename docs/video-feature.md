# Planned video feature

The video feature is an independent domain and must not be coupled to a particular workspace.

When implemented, the feature should use these boundaries:
- `components/`: call surface, participant tiles, device controls and call status.
- `hooks/`: call lifecycle, local device state and room participation.
- `services/`: signaling transport, room API and media-device adapters.
- Workspace permissions decide who may create, invite, join, moderate or end a call. The feature consumes explicit capabilities and participant identities; it does not infer privileges from where it is rendered.
- Keep signaling and media transport replaceable. Do not bind the product to a specific SFU, WebRTC provider or hosting vendor until group size, recording, screen sharing and deployment requirements are defined.

No camera or microphone is accessed until a user explicitly starts or joins a call.
