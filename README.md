# DORA Metrics Collector and Dashboard

A comprehensive solution for collecting, storing, and visualizing DevOps Research and Assessment (DORA) metrics from GitHub repositories. This tool helps engineering teams track key performance indicators to measure software delivery performance.

![DORA Metrics Dashboard](https://i.imgur.com/placeholder-image.png)

## Features

- **Automated Collection**: Collect DORA metrics from GitHub repositories
- **Prometheus Integration**: Store metrics in Prometheus for historical analysis
- **Grafana Dashboard**: Visualize metrics with a pre-configured Grafana dashboard
- **Multi-Repository Support**: Track metrics across multiple repositories
- **Key Metrics Tracking**:
  - Deployment Frequency
  - Lead Time for Changes
  - Change Failure Rate
  - Mean Time to Restore Service

## Installation

### Prerequisites

- Python 3.8+
- Prometheus
- Grafana
- GitHub API access token

### Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/dora-metrics.git
   cd dora-metrics
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

4. **Set up Prometheus**
   
   Ensure Prometheus is configured to scrape metrics from the collector:
   ```yaml
   # Add to prometheus.yml
   scrape_configs:
     - job_name: 'dora_metrics'
       static_configs:
         - targets: ['localhost:8000']
   ```

## Configuration

Create a `.env` file based on `.env.example` with the following variables:


GitHub Configuration

```
GITHUB_TOKEN=your_github_personal_access_token
GITHUB_REPOSITORIES=[{"owner":"username","repo":"frontend"},{"owner":"username","repo":"backend"}]
PORT=8000
```


### GitHub Token Permissions

Your GitHub token needs the following permissions:
- `repo` - Full control of private repositories
- `workflow` - Access to GitHub Actions

## Usage

### Starting the Collector

```bash
python main.py
```

The collector will:
1. Start an HTTP server on the configured port (default: 8000)
2. Begin collecting metrics from configured repositories
3. Update metrics at the configured interval (default: 1 hour)

### Metrics Endpoint

Metrics are available at `http://localhost:8000/metrics` in Prometheus format.

## Grafana Dashboard

Import the dashboard into Grafana:

1. In Grafana, go to Dashboards > Import
2. Upload `dora_metrics_grafana_dashboard.json` or paste its contents
3. Select your Prometheus data source
4. Click Import

The dashboard provides visualizations for:
- Deployment Frequency
- Lead Time for Changes
- Change Failure Rate
- Mean Time to Restore Service
- Deployment Success/Failure rates
- Historical trends

## How DORA Metrics Are Calculated

### Deployment Frequency
Number of successful deployments to production per day.

### Lead Time for Changes
Average time from code commit to successful deployment in production.

### Change Failure Rate
Percentage of deployments that result in a failure requiring remediation.

### Mean Time to Restore
Average time to restore service after a production failure.

## Troubleshooting

### No metrics showing in Prometheus
- Verify the collector is running (`python main.py`)
- Check if metrics endpoint is accessible (`curl http://localhost:8000/metrics`)
- Ensure Prometheus is configured to scrape the metrics endpoint

### GitHub API rate limiting
- The collector implements rate limit handling but may be affected by heavy API usage
- Consider increasing the update interval for repositories with many workflows

### Missing repositories
- Verify repository names and owners in `GITHUB_REPOSITORIES` configuration
- Ensure your GitHub token has access to the specified repositories

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

---

*DORA Metrics reference: Accelerate: The Science of Lean Software and DevOps by Nicole Forsgren, Jez Humble, and Gene Kim*
