var PostsBtn = document.getElementById("posts-btn");
var PostsContainer = document.getElementById("posts-container");

if (PostsBtn) {
  PostsBtn.addEventListener("click", function () {
    console.log('CLicked');
    var ourRequest = new XMLHttpRequest();
    ourRequest.open('GET', 'http://www.xenosystems.net/wp-json/wp/v2/posts?slug=the-cult-of-gnon');
    ourRequest.onload = function () {
      if (ourRequest.status >= 200 && ourRequest.status < 400) {
        var data = JSON.parse(ourRequest.responseText);
        console.log(data);
        createHTML(data);
      } else {
        console.log('We connected to the server, but it returned an error.');
      }
    };

    ourRequest.onerror = function () {
      console.log('Connection error');
    }

    ourRequest.send();
  });
}

function createHTML(postsData) {
  var ourHTMLString = '';
  console.log(postsData[0].slug);

  for (var i = 0; i < postsData.length; i++) {
    ourHTMLString += '<a href="' + postsData[i].link + '"><h2>' + postsData[i].title.rendered + '</h2></a>';
    ourHTMLString += postsData[i].content.rendered;
    var postDate = new Date(postsData[i].date);
    ourHTMLString += '<small>' + Intl.DateTimeFormat('en-US', {
      month: 'long'
    }).format(postDate) + ' ' + postDate.getDate() + ', ' + postDate.getFullYear() + '</small>';
    ourHTMLString += '<hr>'
  }

  PostsContainer.innerHTML = ourHTMLString;
}