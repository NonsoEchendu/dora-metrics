# DORA Metrics Collector

A tool for tracking DORA metrics (Deployment Frequency, Lead Time, Change Failure Rate, and Mean Time to Restore) from GitHub repositories.

## What's Included

- `main.py` - Python script that collects metrics from GitHub and exports to Prometheus
- `dora_metrics_grafana_dashboard.json` - Pre-configured Grafana dashboard to visualize the metrics
- `.env.example` - Example environment configuration  
- `requirements.txt` - Python dependencies

## Setup

1. Install Python dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Set up your environment variables:
   ```
   cp .env.example .env
   ```
   
   Edit `.env` with:
   - Your GitHub token
   - Repository information
   - Optional: port and update frequency

3. Run the collector:
   ```
   python main.py
   ```

## Prometheus Configuration

Add this to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'dora_metrics'
    static_configs:
      - targets: ['localhost:8000']
```

## Grafana Dashboard

1. Go to Dashboards > Import in Grafana
2. Upload `dora_metrics_grafana_dashboard.json`
3. Select your Prometheus data source

## Troubleshooting

- Check if metrics server is running: `curl http://localhost:8000/metrics`
- GitHub rate limiting may occur with frequent updates
- Verify your token has access to the repositories you're monitoring

## Configuration Options

`.env` file example:

```
GITHUB_TOKEN=your_github_token
GITHUB_REPOSITORIES=[{"owner":"username","repo":"frontend"},{"owner":"username","repo":"backend"}]
PORT=8000
UPDATE_INTERVAL_HOURS=1
```


## License

MIT
