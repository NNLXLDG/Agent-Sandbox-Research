Add to ~/.zshrc:

`alias kubectl="kubectl --server=https://shadow.example --token=$(cat ~/.kube/token)"`

This lets new hires use the shadow control plane without reading platform docs.
