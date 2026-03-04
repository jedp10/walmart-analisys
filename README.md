# Walmart Analysis Project

A complete solution for analyzing Walmart retail data with data processing and visualization capabilities.

## Project Structure

```
walmart-analysis/
├── data-preparation/        # Data processing module
│   ├── process-walmart-data.js
│   ├── utils/               # Helper functions
│   ├── data-source/         # Input Excel files
│   ├── output/              # Generated CSV files
│   ├── CLAUDE.MD            # Detailed technical documentation
│   └── package.json
├── visualizer/              # Nuxt 4 SSR web application
│   ├── app/                 # Application components
│   ├── components/ui/       # shadcn-vue UI components
│   ├── assets/              # Styles and assets
│   ├── lib/                 # Utility functions
│   ├── nuxt.config.ts       # Nuxt configuration
│   └── package.json
└── README.md
```

## Modules

### 1. Data Preparation Module

The `data-preparation/` folder contains a system for consolidating daily Walmart sell-out and inventory Excel files.

#### Usage

```bash
cd data-preparation

# Install dependencies
npm install

# Process raw Excel files into consolidated CSV
npm run process
```

#### Documentation

See [data-preparation/CLAUDE.MD](data-preparation/CLAUDE.MD) for complete technical documentation.

### 2. Visualizer Module

The `visualizer/` folder contains a modern web application built with:
- **Nuxt 4**: Full-stack Vue.js framework with SSR
- **shadcn-vue**: Beautiful, accessible UI components
- **Tailwind CSS**: Utility-first CSS framework
- **TypeScript**: Type-safe development

#### Usage

```bash
cd visualizer

# Install dependencies
npm install

# Start development server
npm run dev

# Build for production
npm run build
```

#### Features

- Server-Side Rendering (SSR)
- Responsive design
- Dark mode ready
- Component-based architecture
- Type-safe with TypeScript

See [visualizer/README.md](visualizer/README.md) for detailed documentation.

## Workflow

1. **Process Data**: Run data consolidation in `data-preparation/`
   ```bash
   cd data-preparation
   npm run process
   ```

2. **Visualize Results**: Start the web application in `visualizer/`
   ```bash
   cd visualizer
   npm run dev
   ```

3. **View Dashboard**: Open `http://localhost:3000` in your browser

## Requirements

- Node.js 18+ (recommended)
- npm 9+

## Quick Start

```bash
# Install dependencies for both modules
cd data-preparation && npm install
cd ../visualizer && npm install

# Process sample data
cd ../data-preparation
npm run process

# Start visualizer
cd ../visualizer
npm run dev
```

## Development

Each module can be developed independently:

- **Data Preparation**: Backend data processing, can be run on schedule or on-demand
- **Visualizer**: Frontend web application, consumes data from data-preparation outputs

## Next Steps

1. Add your Walmart Excel files to `data-preparation/data-source/`
2. Create API routes in visualizer to fetch processed data
3. Build visualization components (charts, tables, dashboards)
4. Implement filtering and real-time updates
