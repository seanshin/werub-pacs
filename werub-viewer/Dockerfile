# WeRU.B Viewer — Independent OHIF-based viewer
# Does NOT modify existing OHIF container

FROM nginx:1.24-alpine

COPY dist/ /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY LICENSE /usr/share/nginx/html/LICENSE

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
