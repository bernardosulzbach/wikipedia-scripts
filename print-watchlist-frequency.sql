.mode column
.headers on
.width 40

WITH main_page_statistics AS
         (SELECT name,
                 count(*)  AS occurrences,
                 min(date) AS first_occurrence,
                 max(date) AS last_occurrence
          FROM page_open
          WHERE name NOT LIKE 'Talk:%'
          GROUP BY name),
     talk_pages_statistics AS
         (SELECT substr(name, 6) AS name,
                 count(*)        AS occurrences,
                 min(date)       AS first_occurrence,
                 max(date)       AS last_occurrence
          FROM page_open
          WHERE name LIKE 'Talk:%'
          GROUP BY name)
SELECT name,
       sum(occurrences)                                                                               AS occurrences,
       min(first_occurrence)                                                                          AS first_occurrence,
       max(last_occurrence)                                                                           AS last_occurrence,
       sum(occurrences) /
       ((strftime('%s', datetime('now')) - strftime('%s', min(first_occurrence))) / (24.0 * 60 * 60)) AS times_per_day
FROM (SELECT * FROM talk_pages_statistics UNION SELECT * FROM main_page_statistics)
GROUP BY name
HAVING sum(occurrences) > 1
ORDER BY times_per_day DESC, occurrences DESC, name;
