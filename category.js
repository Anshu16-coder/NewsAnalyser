const config = document.body.dataset;
const API_ENDPOINT = `/api/${config.endpoint}`;
let allArticles = [];
let sentimentChart;

const sentimentDetails = {
    Positive: { icon: 'fa-face-smile', className: 'positive' },
    Negative: { icon: 'fa-face-frown', className: 'negative' },
    Neutral: { icon: 'fa-face-meh', className: 'neutral' }
};

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('date-filter').addEventListener('change', applyFilters);
    document.getElementById('sentiment-filter').addEventListener('change', applyFilters);
    document.getElementById('reset-filter').addEventListener('click', resetFilters);
    fetchArticles();
});

async function fetchArticles() {
    try {
        const response = await fetch(API_ENDPOINT);
        if (!response.ok) {
            if (response.status === 404) {
                const container = document.getElementById('articles-container');
                container.replaceChildren(createState('empty-state', 'fa-newspaper', 'No articles available', 'This category has no articles at the moment.' ));
                document.getElementById('filter-status').innerHTML = '<strong>0 articles</strong> — no articles available';
                return;
            }
            throw new Error(`The live feed returned ${response.status}.`);
        }
        const articles = await response.json();
        allArticles = removeDuplicates(articles.filter(isUsableArticle))
            .sort((a, b) => parseDate(b.datetime_posted) - parseDate(a.datetime_posted));
        populateDateFilter(allArticles);
        applyFilters();
    } catch (error) {
        console.error('Unable to load articles:', error);
        const container = document.getElementById('articles-container');
        container.replaceChildren(createState('empty-state', 'fa-circle-exclamation', 'No articles available', 'This category has no articles at the moment.'));
        document.getElementById('filter-status').innerHTML = '<strong>0 articles</strong> — no articles available';
        updateSentimentAnalysis([]);
    }
}

function isUsableArticle(article) {
    return article && article.headline && article.content;
}

function removeDuplicates(articles) {
    const headlines = new Set();
    return articles.filter(article => {
        const key = article.headline.trim().toLowerCase();
        if (headlines.has(key)) return false;
        headlines.add(key);
        return true;
    });
}

function parseDate(value) {
    if (!value) return new Date(NaN);
    const clean = String(value)
        .replace(/^(Updated:|Published On:|Posted on:)\s*/i, '')
        .replace(/\s*IST\b/i, '');
    return new Date(clean);
}

function dateKey(article) {
    const date = parseDate(article.datetime_posted);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function formatDate(value) {
    const date = parseDate(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
}

function populateDateFilter(articles) {
    const filter = document.getElementById('date-filter');
    filter.length = 1;
    [...new Set(articles.map(dateKey))].sort().reverse().forEach(key => filter.add(new Option(formatDate(key), key)));
}

function applyFilters() {
    const selectedDate = document.getElementById('date-filter').value;
    const selectedSentiment = document.getElementById('sentiment-filter').value;
    const articles = allArticles.filter(article => {
        return (selectedDate === 'all' || dateKey(article) === selectedDate)
            && (selectedSentiment === 'all' || normalizedSentiment(article.analysis_result) === selectedSentiment);
    });
    displayArticles(articles);
    updateSentimentAnalysis(articles);
    updateFilterStatus(articles.length, selectedDate, selectedSentiment);
}

function resetFilters() {
    document.getElementById('date-filter').value = 'all';
    document.getElementById('sentiment-filter').value = 'all';
    applyFilters();
}

function normalizedSentiment(value) {
    return ['Positive', 'Negative'].includes(value) ? value : 'Neutral';
}

function updateFilterStatus(count, date, sentiment) {
    const parts = [];
    if (date !== 'all') parts.push(formatDate(date));
    if (sentiment !== 'all') parts.push(sentiment.toLowerCase());
    const descriptor = parts.length ? ` filtered by ${parts.join(' · ')}` : '';
    document.getElementById('filter-status').innerHTML = `<strong>${count} article${count === 1 ? '' : 's'}</strong>${descriptor}`;
}

function displayArticles(articles) {
    const container = document.getElementById('articles-container');
    container.replaceChildren();
    if (!articles.length) {
        container.append(createState('empty-state', 'fa-newspaper', 'No articles match these filters.', 'Try selecting a different date or sentiment.'));
        return;
    }
    articles.forEach(article => container.append(createArticle(article)));
}

function createArticle(article) {
    const sentiment = normalizedSentiment(article.analysis_result);
    const detail = sentimentDetails[sentiment];
    const card = document.createElement('article');
    card.className = 'article';

    const meta = document.createElement('div');
    meta.className = 'article__meta';
    const date = document.createElement('span');
    date.className = 'article__date';
    date.innerHTML = `<i class="fa-regular fa-calendar"></i> ${formatDate(article.datetime_posted)}`;
    const badge = document.createElement('span');
    badge.className = `sentiment-badge sentiment-badge--${detail.className}`;
    badge.innerHTML = `<i class="fa-solid ${detail.icon}"></i> ${sentiment}`;
    meta.append(date, badge);

    const title = document.createElement('h3');
    title.textContent = article.headline;
    const content = document.createElement('p');
    content.className = 'article__content';
    content.textContent = truncateText(article.content, 240);
    const footer = document.createElement('div');
    footer.className = 'article__footer';
    const link = document.createElement('a');
    link.className = 'article__link';
    link.href = article.link || '#';
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.innerHTML = 'Read full article <i class="fa-solid fa-arrow-up-right-from-square"></i>';
    footer.append(link);
    card.append(meta, title, content, footer);
    return card;
}

function truncateText(text, length) {
    const content = String(text).trim();
    return content.length > length ? `${content.slice(0, length).trimEnd()}…` : content;
}

function createState(className, icon, title, detail) {
    const state = document.createElement('div');
    state.className = className;
    state.innerHTML = `<div><i class="fa-solid ${icon}"></i><p><strong>${title}</strong><br>${detail}</p></div>`;
    return state;
}

function updateSentimentAnalysis(articles) {
    const counts = { Positive: 0, Negative: 0, Neutral: 0 };
    articles.forEach(article => counts[normalizedSentiment(article.analysis_result)]++);
    const total = articles.length;
    document.getElementById('positive-percent').textContent = `${percentage(counts.Positive, total)}%`;
    document.getElementById('negative-percent').textContent = `${percentage(counts.Negative, total)}%`;
    document.getElementById('neutral-percent').textContent = `${percentage(counts.Neutral, total)}%`;
    document.getElementById('total-articles').textContent = total;
    renderChart(counts);
}

function percentage(value, total) {
    return total ? Math.round((value / total) * 100) : 0;
}

function renderChart(counts) {
    const context = document.getElementById('sentiment-chart').getContext('2d');
    if (sentimentChart) sentimentChart.destroy();
    sentimentChart = new Chart(context, {
        type: 'doughnut',
        data: {
            labels: ['Positive', 'Negative', 'Neutral'],
            datasets: [{
                data: [counts.Positive, counts.Negative, counts.Neutral],
                backgroundColor: ['#0ca30c', '#d03b3b', '#525870'],
                borderColor: '#E8E7F7',
                borderWidth: 3,
                hoverOffset: 5
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '68%',
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { usePointStyle: true, boxWidth: 9, padding: 15, color: '#626780', font: { family: 'Inter, system-ui', size: 12, weight: '600' } }
                },
                tooltip: {
                    callbacks: { label: context => `${context.label}: ${context.raw} article${context.raw === 1 ? '' : 's'}` }
                }
            }
        }
    });
}
