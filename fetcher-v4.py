# import urllib for fetching html and BeautifulSoup to parse it
import urllib.request
import urllib.parse
from bs4 import BeautifulSoup, NavigableString

# basic html code
book_code = BeautifulSoup(
    '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Reignition</title><meta name="description" content="Reignition"><meta name="author" content="Nick Land"></head><body></body></html>', 'html5lib')

# reading input file
file1 = open('INPUT2.txt', 'r')
Lines = file1.readlines()

# debug file - shows if urls have been successfully accessed
r = open('results.txt', 'w+')

# main loop - goes through each line of the input file
for line in Lines:
    # book title
    if line[0] == '$':
        line.strip()
        main_title_tag = book_code.new_tag('h1', **{'class': 'book-title'})
        main_title_tag.append(line[1:])
        book_code.body.append(main_title_tag)
    # tome title
    elif line[0] == '%':
        line.strip()
        tome_title_tag = book_code.new_tag('h1', **{'class': 'tome-title'})
        tome_title_tag.append(line[1:])
        book_code.body.append(tome_title_tag)
    # block title
    elif line[0] == '*':
        line.strip()
        block_title_tag = book_code.new_tag('h1', **{'class': 'block-title'})
        block_title_tag.append(line[1:])
        book_code.body.append(block_title_tag)
    # section title
    elif line[0] == '=':
        line.strip()
        section_title_tag = book_code.new_tag(
            'h2', **{'class': 'section-title'})
        section_title_tag.append(line[1:])
        book_code.body.append(section_title_tag)
    # sequence title
    elif line[0] == '&':
        line.strip()
        sequence_title_tag = book_code.new_tag(
            'h3', **{'class': 'sequence-title'})
        sequence_title_tag.append(line[1:])
        book_code.body.append(sequence_title_tag)
    # chapter title
    elif line[0] == '#':
        line.strip()
        chapter_title_tag = book_code.new_tag(
            'h3', **{'class': 'chapter-title'})
        chapter_title_tag.append(line[1:])
        book_code.body.append(chapter_title_tag)
    # post content
    elif line[0] == '-':
        # grab url
        new_line = line[1:].strip().split('|')
        post_url = new_line[1]
        r.write(post_url+' - ')
        # acces url
        req = urllib.request.Request(
            post_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; Win64; x64)'})
        webUrl_post = urllib.request.urlopen(req)
        # check
        r.write("result code: " + str(webUrl_post.getcode()) + '\n')
        # get html and make it accessible
        post_html = webUrl_post.read()
        post_init = BeautifulSoup(post_html, 'html5lib')
        post_init.prettify()
        # get domain
        domain = urllib.parse.urlparse(post_url).netloc
        post_title = ''
        post_content = ''
        post_date = ''
        title_content = ''
        date_content = ''
        # sort through domains to get title, content and date
        if domain == 'oldnicksite.wordpress.com':
            post_title = post_init.find(class_="entry-title")
            title_content = str(post_title.contents[0])
            post_content = post_init.select('.entry-content > p')
            post_date = post_init.find(class_="entry-date published")
            date_content = str(post_date.contents[0])
        elif domain == 'www.uf-blog.net':
            post_title = post_init.find(class_="entry-title")
            title_content = str(post_title.contents[0])
            post_content = post_init.select('.entry-content > p')
            post_date = post_init.find(class_="entry-date")
            date_content = str(post_date.contents[0])
        elif domain == 'www.xenosystems.net':
            post_title = post_init.select(".post > h2")
            title_content = str(post_title[0].contents[0])
            post_content = post_init.select('.entry > p')
            post_date = post_init.find(class_="time")
            date_content = str(post_date.contents[0])
        elif domain == 'jacobitemag.com':
            post_title = post_init.find(class_="post-title")
            title_content = str(post_title.contents[0])
            post_content = post_init.select('.article-content > p')
            post_date = post_init.find(class_="date")
            date_content = str(post_date.contents[0])
        elif domain == 'www.wdw.nl':
            post_title = post_init.find(class_="review-header-title")
            title_content = str(post_title.contents[0])
            post_content = post_init.select('.review-body')
            post_date = post_init.find(class_="review-header-date")
            date_content = str(post_date.contents[0])
        elif domain == 'www.urbanomic.com':
            post_title = post_init.find(class_="mag_scroll_title")
            title_content = str(post_title.contents[0])
            post_content = post_init.select('.entry-content')
            post_date = '2016'
            date_content = post_date
        # adding to book html
        post_title_link_tag = book_code.new_tag(
            'a', href=post_url)
        post_title_tag = book_code.new_tag(
            'h4', **{'class': 'post-title'})
        post_title_tag.append(title_content)
        post_title_link_tag.append(post_title_tag)
        book_code.body.append(post_title_link_tag)
        print(post_title_link_tag)
        for p in post_content:
            book_code.body.append(p)
            print(p)
        post_date_tag = book_code.new_tag(
            'small', **{'class': 'post-date'})
        post_date_tag.append(date_content)
        book_code.body.append(post_date_tag)
        print(post_date_tag)


r.close()

book_code.prettify()

# print to html file
f = open('reignition.html', 'w+')

f.write(str(book_code))

f.close()
