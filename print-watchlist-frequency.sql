.mode column
.headers on
.width 80

SELECT name,
       count(*)                                                                                      AS occurrences,
       min(date)                                                                                     AS first_occurrence,
       max(date)                                                                                     AS last_occurrence,
       count(*) / ((strftime('%s', datetime('now')) - strftime('%s', min(date))) / (24.0 * 60 * 60)) AS times_per_day
FROM page_open
GROUP BY name
HAVING count(*) > 1
ORDER BY times_per_day DESC, occurrences DESC, name;
