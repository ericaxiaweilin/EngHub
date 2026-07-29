#!/usr/bin/env python3
import yaml
import os

# Read the current config
config_path = "/Users/thanhhuyennguyen/.agnes/config/config.yaml"
with open(config_path, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

# Update active provider to litellm
config['active_provider'] = 'litellm'

# Add/update litellm provider with server gateway
config['providers']['litellm'] = {
    'enabled': True,
    'type': 'openai-compatible',
    'model': 'deepseek-v4-pro',  # Using default model (can be configured)
    'gateway_url': 'http://100.96.188.77:14041',
    'api_key': '',  # Empty or use specific key if needed
    'configured': True
}

# Keep the agnes provider for fallback
if 'agnes' not in config['providers']:
    config['providers']['agnes'] = {
        'enabled': False,  # Disabled when using litellm
        'model': 'agnes-2.5-flash',
        'configured': True
    }

# Write back to file
with open(config_path, 'w', encoding='utf-8') as f:
    yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

print("✅ Config updated successfully!")
print(f"\nNew configuration:")
print(f"active_provider: litellm")
print(f"litellm provider: gateway={config['providers']['litellm'].get('gateway_url')}, model={config['providers']['litellm'].get('model')}")