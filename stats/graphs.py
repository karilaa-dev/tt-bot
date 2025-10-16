import asyncio
import logging
from datetime import datetime
from typing import List, Tuple, Optional

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from sqlalchemy import text, func

from data.database import get_session
from data.models import Users, Video, Music
from misc.utils import tCurrent

# Configure plotly for static image generation
pio.kaleido.scope.mathjax = None


def create_time_series_plot(
    days: List[datetime], 
    amounts: List[int], 
    title: str
) -> bytes:
    """Create an optimized time series plot using Plotly."""
    
    fig = go.Figure()
    
    if not days or not amounts:
        fig.add_annotation(
            text="No data available for this period",
            xref="paper", yref="paper",
            x=0.5, y=0.5,
            showarrow=False,
            font=dict(size=16)
        )
    else:
        # Add main line
        fig.add_trace(go.Scatter(
            x=days,
            y=amounts,
            mode='lines+markers',
            line=dict(color='#1f77b4', width=2),
            marker=dict(
                color='#1f77b4',
                size=6,
                symbol='circle'
            ),
            name='Count'
        ))
        
        # Highlight points with values > 0
        if any(amount > 0 for amount in amounts):
            highlight_days = [day for day, amount in zip(days, amounts) if amount > 0]
            highlight_amounts = [amount for amount in amounts if amount > 0]
            
            fig.add_trace(go.Scatter(
                x=highlight_days,
                y=highlight_amounts,
                mode='markers',
                marker=dict(
                    color='#ff7f0e',
                    size=8,
                    symbol='diamond'
                ),
                name='Active Points',
                showlegend=False
            ))
    
    # Update layout for better appearance
    fig.update_layout(
        title=dict(
            text=title,
            x=0.5,
            font=dict(size=18)
        ),
        xaxis_title="Date",
        yaxis_title="Number of Users",
        template="plotly_white",
        width=1200,
        height=600,
        margin=dict(l=60, r=40, t=80, b=80),
        showlegend=False,
        hovermode='x unified'
    )
    
    # Format x-axis for better date display
    fig.update_xaxes(
        tickangle=45,
        tickformat='%Y-%m-%d',
        showgrid=True,
        gridcolor='lightgray'
    )
    
    fig.update_yaxes(
        showgrid=True,
        gridcolor='lightgray'
    )
    
    # Generate image bytes
    return pio.to_image(fig, format='png', engine='kaleido')


async def get_time_series_data(
    table_name: str,
    period: int,
    id_condition: str
) -> List[int]:
    """Optimized data retrieval for time series."""
    
    # Map table to model and time column
    table_mapping = {
        'users': (Users, Users.registered_at),
        'videos': (Video, Video.downloaded_at),
        'music': (Music, Music.downloaded_at)
    }
    
    model, time_column = table_mapping.get(table_name, (Users, Users.registered_at))
    
    async with await get_session() as db:
        from sqlalchemy import select
        
        stmt = select(time_column).where(
            time_column <= tCurrent() // 86400 * 86400,
            time_column > period,
            text(id_condition)
        )
        result = await db.execute(stmt)
        return [row[0] for row in result.all()]


def process_time_series_data(
    timestamps: List[int],
    depth: str,
    period: int
) -> Tuple[List[datetime], List[int]]:
    """Process raw timestamps into grouped time series data."""
    
    if not timestamps:
        return [], []
    
    # Convert to DataFrame for efficient processing
    df = pd.DataFrame({"timestamp": timestamps})
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")
    
    # Group by specified time depth
    df_grouped = df.groupby(df["datetime"].dt.strftime(depth)).size().reset_index()
    df_grouped.columns = ["time_str", "count"]
    
    # Create complete date range
    start_date = datetime.fromtimestamp(period)
    end_date = datetime.fromtimestamp(tCurrent() // 86400 * 86400)
    
    # Generate date range based on depth
    freq_map = {
        '%Y-%m-%d': 'D',
        '%Y-%m': 'M', 
        '%Y': 'Y',
        '%Y-%m-%d %H': 'H'
    }
    freq = freq_map.get(depth, 'D')
    
    date_range = pd.date_range(start=start_date, end=end_date, freq=freq)
    df_date_range = pd.DataFrame({"time_str": date_range.strftime(depth)})
    
    # Merge and fill missing values
    df_merged = df_date_range.merge(df_grouped, on="time_str", how="left").fillna(0)
    
    # Filter out zero values for cleaner plot
    df_filtered = df_merged[df_merged["count"] > 0].reset_index(drop=True)
    
    # Convert to lists
    days = [datetime.strptime(time_str, depth) for time_str in df_filtered["time_str"]]
    amounts = df_filtered["count"].tolist()
    
    return days, amounts


async def plot_user_graph(
    graph_name: str,
    depth: str,
    period: int,
    id_condition: str,
    table_name: str
) -> bytes:
    """Main function to create user activity graphs."""
    
    try:
        # Get raw data
        timestamps = await get_time_series_data(table_name, period, id_condition)
        
        # Process data
        days, amounts = process_time_series_data(timestamps, depth, period)
        
        # Create plot in thread pool for better performance
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, 
            lambda: create_time_series_plot(days, amounts, graph_name)
        )
        
    except Exception as e:
        logging.error(f"Error in plot_user_graph: {e}")
        # Return empty plot on error
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: create_time_series_plot([], [], graph_name)
        )


async def plot_async(
    graph_name: str,
    depth: str,
    period: int,
    id_condition: str,
    table: str
) -> bytes:
    """Async wrapper for plot creation."""
    
    try:
        return await plot_user_graph(graph_name, depth, period, id_condition, table)
    except Exception as e:
        logging.error(f"Error in plot_async: {e}")
        raise